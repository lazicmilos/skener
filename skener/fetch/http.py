"""Nivo 1: dohvatanje i sklapanje `SiteSnapshot` (§4, §8).

Jedini sloj nivoa 1 koji dodiruje mrežu. Provere odavde ne uvoze ništa — dobijaju
gotov snapshot (§2.1).

Dva semafora (§8.1): globalni ograničava tebe, po-hostu štiti njih. Po-hostu je
uvek 1 i to je granica između alata i napada.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import socket
import ssl
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from skener import __version__, store
from skener.config import get
from skener.fetch import page as page_builder
from skener.fetch import robots as robots_parser
from skener.fetch import sitemap as sitemap_parser
from skener.fetch.urls import host_of, normalize
from skener.models import (
    Budget,
    DomainInput,
    Entry,
    RobotsInfo,
    SitemapInfo,
    SiteSnapshot,
    SnapshotError,
    Soft404,
    Soft404Probe,
    Tls,
)

log = logging.getLogger("skener.fetch")

# Statusi na koje se odustaje od domena za ovaj prolaz (§8.3) — ne pokušava se ponovo.
ODUSTANI_STATUSI = {429, 503}
PROBE_SUFFIXES = ("", ".html")


@dataclass
class Outcome:
    """Ishod jednog zahteva. Nikad izuzetak — orkestrator vidi samo objekte (§8.2)."""

    url: str
    status: int | None = None
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    elapsed_ms: int = 0
    error_kind: str | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and self.error_kind is None


class DomainBudget:
    """Tvrd budžet po domenu (§4.2): 16 zahteva i 25 sekundi.

    Kad se potroši, ono što je prikupljeno ide dalje, ostalo je `unknown`.
    """

    def __init__(self, max_requests: int, max_seconds: float) -> None:
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self.started = time.monotonic()
        self.requests_made = 0
        self.aborted_reason: str | None = None

    def take(self) -> bool:
        if self.aborted_reason:
            return False
        if self.requests_made >= self.max_requests:
            self.aborted_reason = f"potrošen budžet od {self.max_requests} zahteva"
            return False
        if time.monotonic() - self.started >= self.max_seconds:
            self.aborted_reason = f"potrošen budžet od {self.max_seconds:g} s"
            return False
        self.requests_made += 1
        return True

    def abort(self, reason: str) -> None:
        self.aborted_reason = self.aborted_reason or reason

    def snapshot(self) -> Budget:
        return Budget(
            max_requests=self.max_requests,
            requests_made=self.requests_made,
            elapsed_ms=int((time.monotonic() - self.started) * 1000),
            exhausted=bool(self.aborted_reason),
            aborted_reason=self.aborted_reason,
        )


def _classify(exc: Exception) -> tuple[str, str]:
    """Mrežni izuzetak → (vrsta, detalj). Vrsta odlučuje da li se ponavlja (§4.6)."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__

    for link in chain:
        if isinstance(link, socket.gaierror):
            return "dns", str(link)
        if isinstance(link, ssl.SSLCertVerificationError):
            return "tls", str(link)
        if isinstance(link, ssl.SSLError):
            return "tls", str(link)
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout", str(exc)
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout", str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", str(exc)
    if isinstance(exc, httpx.TooManyRedirects):
        return "too_many_redirects", str(exc)
    return "connection", f"{type(exc).__name__}: {exc}"


class Fetcher:
    """Deli semafore i konekcije između svih domena u prolazu."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._global = asyncio.Semaphore(get(config, "http.concurrency"))
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next_allowed: dict[str, float] = {}
        self._delay_range = [ms / 1000 for ms in get(config, "http.delay_ms")]
        self._client: httpx.AsyncClient | None = None
        self._insecure: httpx.AsyncClient | None = None

    # ---------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> Fetcher:
        self._client = self._make_client(verify=True)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        for client in (self._client, self._insecure):
            if client is not None:
                await client.aclose()

    def _make_client(self, *, verify: bool) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=verify,
            follow_redirects=True,
            headers={"User-Agent": get(self.config, "http.user_agent")},
            timeout=httpx.Timeout(
                get(self.config, "http.timeout_total_s"),
                connect=get(self.config, "http.timeout_connect_s"),
                read=get(self.config, "http.timeout_read_s"),
            ),
            limits=httpx.Limits(max_connections=get(self.config, "http.concurrency") * 2),
        )

    def _pick_client(self, *, verify: bool) -> httpx.AsyncClient:
        if verify:
            assert self._client is not None, "Fetcher se koristi van `async with`"
            return self._client
        if self._insecure is None:
            self._insecure = self._make_client(verify=False)
        return self._insecure

    # ----------------------------------------------------------------- requests
    async def request(
        self,
        url: str,
        budget: DomainBudget,
        *,
        verify: bool = True,
        crawl_delay: float | None = None,
        retries: int = 1,
    ) -> Outcome:
        if not budget.take():
            return Outcome(url=url, error_kind="budget", error_detail=budget.aborted_reason)

        host = host_of(url) or url
        lock = self._host_locks.setdefault(host, asyncio.Lock())

        # Pauza se čeka pod ključem hosta ali van globalnog semafora, da spavanje
        # ne drži slot koji drugi domen može da koristi.
        async with lock:
            await self._wait_turn(host, crawl_delay)
            async with self._global:
                # Meri se samo rad servera. Čekanje u redu i pauza pristojnosti su naše
                # vreme — sa njima „početna odgovara > 1500 ms" pali svakome (§6).
                started = time.monotonic()
                outcome = await self._send(url, verify=verify)
                outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._host_next_allowed[host] = time.monotonic() + random.uniform(*self._delay_range)

        if outcome.status in ODUSTANI_STATUSI:
            budget.abort(f"server vratio {outcome.status}, odustajem od domena za ovaj prolaz")
            return outcome
        if retries > 0 and _should_retry(outcome):
            await asyncio.sleep(random.uniform(0.5, 1.5))
            return await self.request(
                url, budget, verify=verify, crawl_delay=crawl_delay, retries=retries - 1
            )
        return outcome

    async def _wait_turn(self, host: str, crawl_delay: float | None) -> None:
        earliest = self._host_next_allowed.get(host, 0.0)
        if crawl_delay:
            max_delay = get(self.config, "http.max_crawl_delay_s")
            earliest = max(earliest, self._host_next_allowed.get(host, 0.0) + min(crawl_delay, max_delay))
        wait = earliest - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _send(self, url: str, *, verify: bool) -> Outcome:
        client = self._pick_client(verify=verify)
        try:
            response = await client.get(url)
        except Exception as exc:  # noqa: BLE001 — izuzetak nikad ne napušta domen (§8.2)
            kind, detail = _classify(exc)
            return Outcome(url=url, error_kind=kind, error_detail=detail)

        chain = [str(r.request.url) for r in response.history] + [str(response.url)]
        return Outcome(
            url=url,
            status=response.status_code,
            final_url=str(response.url),
            redirect_chain=chain,
            headers=dict(response.headers),
            body=response.content,
        )


def _should_retry(outcome: Outcome) -> bool:
    """4xx je odgovor, ne greška — bez ponovnog pokušaja (§4.6)."""
    if outcome.error_kind in {"connect_timeout", "read_timeout", "timeout", "connection"}:
        return True
    return outcome.status is not None and 500 <= outcome.status < 600


# --------------------------------------------------------------------------- #
# Prolaz nad jednim domenom
# --------------------------------------------------------------------------- #
async def fetch_site(fetcher: Fetcher, target: DomainInput) -> SiteSnapshot:
    """Sklapa `SiteSnapshot`. Izuzetak nikad ne napušta ovu funkciju (§8.2)."""
    cfg = fetcher.config
    domain = target.domain
    budget = DomainBudget(
        get(cfg, "http.max_requests_per_domain"), get(cfg, "http.max_seconds_per_domain")
    )
    snapshot = SiteSnapshot(
        domain=domain,
        industry=target.industry,
        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        scanner_version=__version__,
    )

    entry_outcome, tls_error = await _fetch_entry(fetcher, domain, budget, snapshot)
    snapshot.entry = _entry_from(entry_outcome, tls_error)
    verify = tls_error is None
    if entry_outcome.error_kind == "dns":
        snapshot.budget = budget.snapshot()
        return snapshot

    home = page_builder.build(
        entry_outcome.url,
        final_url=entry_outcome.final_url,
        status=entry_outcome.status,
        headers=entry_outcome.headers,
        body=entry_outcome.body,
        elapsed_ms=entry_outcome.elapsed_ms,
        redirect_hops=max(len(entry_outcome.redirect_chain) - 1, 0),
        keep_raw_html=True,
    )
    snapshot.pages.append(home)
    base_url = home.final_url or home.url
    # Sve dalje adrese idu sa *konačnog* porekla: ako je domen preusmerio na www
    # ili na https, robots i sitemap žive tamo, ne na traženoj adresi.
    origin = _origin_of(base_url)

    rules = await _fetch_robots(fetcher, origin, budget, snapshot, verify=verify)
    crawl_delay = rules.crawl_delay
    candidates = await _collect_sitemap(
        fetcher, origin, budget, snapshot, rules, verify=verify, crawl_delay=crawl_delay
    )
    if not candidates:
        candidates = page_builder.internal_links(home.raw_html, base_url)
        snapshot.sample_source = "links" if candidates else "none"
    else:
        snapshot.sample_source = "sitemap"

    # Alat koji prijavljuje da robots.txt nedostaje, a ignoriše ga kad postoji,
    # je nekonzistentan na način koji se primeti (§4.3).
    allowed = [url for url in candidates if robots_parser.allows(rules, url)]
    sample = sitemap_parser.sample(base_url, allowed, get(cfg, "sitemap.sample_size"))

    # Sonde idu pre uzorka: dva zahteva za `high` nalaz. Posle uzorka ih velika mapa
    # sajta (Yoast indeks sa 9 mapa) ostavi bez budžeta.
    # Idu na poreklo, ne na putanju početne: `/index.php/<token>` na PHP-u vraća 200
    # preko PATH_INFO-a i daje lažni `infra.soft404` (§5.2).
    await _probe_soft404(
        fetcher, domain, origin, budget, snapshot, verify=verify, crawl_delay=crawl_delay
    )
    await _fetch_sample(fetcher, sample[1:], budget, snapshot, verify=verify, crawl_delay=crawl_delay)

    snapshot.budget = budget.snapshot()
    return snapshot


def _origin_of(url: str) -> str:
    parts = httpx.URL(url)
    return f"{parts.scheme}://{parts.netloc.decode()}"


def entry_candidates(domain: str) -> list[str]:
    """Adrese kojima se pokušava ulaz, redom.

    Domen sme da bude i pun origin (`http://localhost:8123`) — korisno za staging
    sa portom, i jedini način da se fetcher testira protiv lokalnog servera.
    """
    if "://" in domain:
        return [domain if domain.endswith("/") else f"{domain}/"]
    return [f"https://{domain}/", f"http://{domain}/"]


async def _fetch_entry(
    fetcher: Fetcher, domain: str, budget: DomainBudget, snapshot: SiteSnapshot
) -> tuple[Outcome, str | None]:
    """https pa http; nevalidan sertifikat je nalaz, ne razlog da domen ispadne (§4.6).

    Vraća i TLS grešku (`None` = sertifikat prošao): ponovni dohvat bez provere
    uspe bez greške, pa bi razlog iz dokaza inače nestao.
    """
    candidates = entry_candidates(domain)
    outcome = await fetcher.request(candidates[0], budget)

    if outcome.error_kind == "tls":
        # Istekao sertifikat je vredan nalaz za prodaju i najgori mogući razlog
        # da ti ceo domen ispadne iz izveštaja — zato se dohvat ponavlja bez provere.
        snapshot.errors.append(SnapshotError("entry", "tls", outcome.error_detail or ""))
        retry = await fetcher.request(candidates[0], budget, verify=False)
        return (retry if retry.ok else outcome), outcome.error_detail or "nepoznata TLS greška"

    if not outcome.ok and outcome.error_kind not in {"dns", "budget"} and len(candidates) > 1:
        snapshot.errors.append(SnapshotError("entry", outcome.error_kind or "?", outcome.error_detail or ""))
        fallback = await fetcher.request(candidates[1], budget)
        if fallback.ok:
            return fallback, None
    return outcome, None


def _entry_from(outcome: Outcome, tls_error: str | None) -> Entry:
    return Entry(
        requested_url=outcome.url,
        final_url=outcome.final_url,
        redirect_chain=outcome.redirect_chain,
        status=outcome.status,
        elapsed_ms=outcome.elapsed_ms,
        tls=Tls(valid=tls_error is None, error=tls_error),
        error_kind=outcome.error_kind,
        error_detail=outcome.error_detail,
    )


async def _fetch_robots(
    fetcher: Fetcher, origin: str, budget: DomainBudget, snapshot: SiteSnapshot, *, verify: bool
) -> robots_parser.RobotsRules:
    outcome = await fetcher.request(f"{origin}/robots.txt", budget, verify=verify, retries=0)
    body = outcome.body.decode("utf-8", errors="replace") if outcome.ok and outcome.body else None
    rules = robots_parser.parse(body if outcome.status == 200 else None)
    snapshot.robots = RobotsInfo(
        status=outcome.status,
        body=body if outcome.status == 200 else None,
        disallow=list(rules.disallow),
        allow=list(rules.allow),
        crawl_delay=rules.crawl_delay,
        sitemaps=list(rules.sitemaps),
        error=outcome.error_detail,
    )
    if outcome.error_kind:
        snapshot.errors.append(SnapshotError("robots", outcome.error_kind, outcome.error_detail or ""))
    return rules


async def _collect_sitemap(
    fetcher: Fetcher,
    origin: str,
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    rules: robots_parser.RobotsRules,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> list[str]:
    """Rekurzija kroz `sitemapindex` sa ograničenjima iz §4.4."""
    cfg = fetcher.config
    max_depth = get(cfg, "sitemap.max_depth")
    max_files = get(cfg, "sitemap.max_files")
    max_urls = get(cfg, "sitemap.max_urls")

    # `Sitemap:` iz robots.txt ima prednost nad pogađanjem (§4.3).
    start = list(rules.sitemaps) or [f"{origin}/sitemap.xml"]
    info = SitemapInfo(url=start[0])
    queue: list[tuple[str, int]] = [(url, 0) for url in start]
    seen: set[str] = set()
    collected: list[str] = []
    files_read = 0

    while queue and files_read < max_files and len(collected) < max_urls:
        url, depth = queue.pop(0)
        canonical = normalize(url)
        if not canonical or canonical in seen or depth > max_depth:
            continue
        seen.add(canonical)

        outcome = await fetcher.request(
            canonical, budget, verify=verify, crawl_delay=crawl_delay, retries=0
        )
        if info.status is None or canonical == normalize(start[0]):
            info.status = outcome.status
        if outcome.error_kind == "budget":
            break
        files_read += 1
        if not outcome.ok or outcome.status != 200:
            continue

        kind, locations = sitemap_parser.parse(outcome.body)
        info.depth_reached = max(info.depth_reached, depth)
        if kind == "index":
            info.nested_count += len(locations)
            queue.extend((loc, depth + 1) for loc in locations)
        elif kind == "urlset":
            room = max_urls - len(collected)
            collected.extend(locations[:room])
            if len(locations) > room:
                info.truncated = True

    info.urls = collected
    snapshot.sitemap = info
    return collected


async def _fetch_sample(
    fetcher: Fetcher,
    urls: Sequence[str],
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> None:
    for url in urls:
        outcome = await fetcher.request(url, budget, verify=verify, crawl_delay=crawl_delay)
        if outcome.error_kind == "budget":
            break
        snapshot.pages.append(
            page_builder.build(
                url,
                final_url=outcome.final_url,
                status=outcome.status,
                headers=outcome.headers,
                body=outcome.body,
                elapsed_ms=outcome.elapsed_ms,
                redirect_hops=max(len(outcome.redirect_chain) - 1, 0),
            )
        )


def probe_urls(domain: str, origin: str) -> list[str]:
    """Determinističke sonde po §5.2 — `sha1(domain)[:16]`, da testovi budu ponovljivi."""
    token = hashlib.sha1(domain.encode()).hexdigest()[:16]
    base = origin.rstrip("/")
    return [f"{base}/{token}{suffix}" for suffix in PROBE_SUFFIXES]


async def _probe_soft404(
    fetcher: Fetcher,
    domain: str,
    origin: str,
    budget: DomainBudget,
    snapshot: SiteSnapshot,
    *,
    verify: bool,
    crawl_delay: float | None,
) -> None:
    probes: list[Soft404Probe] = []
    for url in probe_urls(domain, origin):
        outcome = await fetcher.request(
            url, budget, verify=verify, crawl_delay=crawl_delay, retries=0
        )
        if outcome.error_kind == "budget":
            break
        sample = ""
        if outcome.ok and outcome.body:
            sample = page_builder.build(
                url, final_url=outcome.final_url, status=outcome.status, body=outcome.body
            ).text_sample
        probes.append(
            Soft404Probe(
                url=url,
                status=outcome.status,
                final_url=outcome.final_url,
                text_sample=sample,
                error=outcome.error_detail,
            )
        )
    snapshot.soft404 = Soft404(probes=probes)


# --------------------------------------------------------------------------- #
# Prolaz nad listom domena
# --------------------------------------------------------------------------- #
async def scan_domains(
    targets: Iterable[DomainInput], config: dict, snapshot_dir: Path | None = None
) -> list[SiteSnapshot]:
    """Snapshot ide na disk čim je domen gotov — ako proces pukne na 190., imaš 189 (§8.2)."""
    targets = list(targets)
    results: list[SiteSnapshot] = []
    # Budžet od 25 s je za rad na domenu, ne za čekanje u redu iza ostalih 199:
    # `DomainBudget` nastaje u `fetch_site`, pa domen ulazi tamo tek kad dobije red.
    in_flight = asyncio.Semaphore(get(config, "http.domain_concurrency"))

    async with Fetcher(config) as fetcher:

        async def one(target: DomainInput) -> SiteSnapshot:
            async with in_flight:
                log.info("nivo 1 počinje", extra={"domain": target.domain})
                try:
                    snapshot = await fetch_site(fetcher, target)
                except Exception as exc:  # noqa: BLE001 — granica domena
                    log.error("nivo 1 pukao: %s", exc, extra={"domain": target.domain})
                    snapshot = SiteSnapshot(
                        domain=target.domain,
                        industry=target.industry,
                        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        errors=[SnapshotError("fetch", type(exc).__name__, str(exc))],
                    )
                if snapshot_dir is not None:
                    store.write_site(snapshot_dir, snapshot)
                log.info(
                    "nivo 1 gotov: %d stranica, %d zahteva",
                    len(snapshot.pages),
                    snapshot.budget.requests_made,
                    extra={"domain": target.domain},
                )
                return snapshot

        # Goli `gather` bi jednim izuzetkom oborio ceo prolaz — tačno greška iz §8.2.
        gathered = await asyncio.gather(*(one(t) for t in targets), return_exceptions=True)

    for target, item in zip(targets, gathered, strict=True):
        if isinstance(item, BaseException):
            log.error("domen izgubljen: %r", item, extra={"domain": target.domain})
            results.append(SiteSnapshot(domain=target.domain, industry=target.industry))
        else:
            results.append(item)
    return results
