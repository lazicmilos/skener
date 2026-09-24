"""Nivo 2: Playwright, sklapanje `BrowserSnapshot` (§7).

Playwright se uvozi lenjo, da alat radi i kad nivo 2 nije instaliran.

Najozbiljnija zamka u projektu je merenje težine. `encodedBodySize` iz
Performance API-ja vraća 0 za resurse sa drugog porekla bez `Timing-Allow-Origin`,
pa sajt sa svim slikama na CDN-u ispadne težak 2 kB. Zato se ovde sluša mrežni
saobraćaj i sabiraju stvarni odgovori (§7.2).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skener import __version__, store
from skener.config import get, user_agent
from skener.models import (
    BrowserSnapshot,
    ConsoleStats,
    DomStats,
    NetworkStats,
    OversizedImage,
    SiteSnapshot,
    SnapshotError,
    TimingStats,
)

log = logging.getLogger("skener.browser")

CONSOLE_SAMPLES = 5
CLOSE_TIMEOUT_S = 10
# Odgovori bez tela po definiciji — nisu „nemereni", njihova veličina je poznata i nula.
BEZ_TELA = {204, 304}

_SCROLL = """
async () => {
  await new Promise((resolve) => {
    let moved = 0;
    const step = () => {
      window.scrollBy(0, window.innerHeight);
      moved += window.innerHeight;
      if (moved < document.body.scrollHeight && moved < 50000) setTimeout(step, 100);
      else resolve();
    };
    step();
  });
  window.scrollTo(0, 0);
}
"""

_DOM = """
(ratio) => {
  const images = Array.from(document.images);
  let withoutAlt = 0, emptyAlt = 0, unmeasured = 0;
  const oversized = [];
  for (const img of images) {
    // Tri stanja, ne dva: nema atributa je greška, alt="" je ispravno.
    if (!img.hasAttribute('alt')) withoutAlt++;
    else if (img.getAttribute('alt').trim() === '') emptyAlt++;

    const cw = img.clientWidth, ch = img.clientHeight;
    const nw = img.naturalWidth, nh = img.naturalHeight;
    if (cw === 0 || nw === 0) { unmeasured++; continue; }
    if (nw / cw > ratio) {
      oversized.push({ src: img.currentSrc || img.src, nw, nh, cw, ch, ratio: nw / cw });
    }
  }
  return {
    h1: document.querySelectorAll('h1').length,
    total: images.length,
    withoutAlt, emptyAlt, unmeasured, oversized,
  };
}
"""

_TIMING = """
() => {
  const nav = performance.getEntriesByType('navigation')[0];
  if (!nav) return null;
  return {
    dcl: Math.round(nav.domContentLoadedEventEnd) || null,
    load: Math.round(nav.loadEventEnd) || null,
  };
}
"""


class _Recorder:
    """Sabira stvarne odgovore dok stižu (§7.2)."""

    def __init__(self) -> None:
        self.request_count = 0
        self.total_bytes = 0
        self.by_type: dict[str, int] = {}
        self.unmeasured = 0
        self.bytes_by_url: dict[str, int] = {}
        self.console_errors = 0
        self.console_warnings = 0
        self.samples: list[str] = []
        self._tasks: list[asyncio.Task] = []

    def on_request(self, _request: Any) -> None:
        self.request_count += 1

    def on_response(self, response: Any) -> None:
        self._tasks.append(asyncio.create_task(self._measure(response)))

    def on_console(self, message: Any) -> None:
        if message.type == "error":
            self.console_errors += 1
            if len(self.samples) < CONSOLE_SAMPLES:
                self.samples.append(message.text[:300])
        elif message.type == "warning":
            self.console_warnings += 1

    def on_page_error(self, error: Any) -> None:
        self.console_errors += 1
        if len(self.samples) < CONSOLE_SAMPLES:
            self.samples.append(str(error)[:300])

    async def _measure(self, response: Any) -> None:
        url = response.url
        # `data:` i `blob:` su već u HTML-u — brojanjem ih dupliraš (§7.2).
        if url.startswith(("data:", "blob:")):
            return
        status = response.status
        # Preusmerenja nemaju telo; brojati ih kao „nemerena" bi lažno podiglo prag.
        if 300 <= status < 400:
            return

        size: int | None = 0 if status in BEZ_TELA else None
        if size is None:
            try:
                # `response.body()` baca za odgovore iz keša i prekinute (§15, zamka 11).
                size = len(await response.body())
            except Exception:  # noqa: BLE001
                header = response.headers.get("content-length")
                size = int(header) if header and header.isdigit() else None

        if size is None:
            # Ne broj nulu — nula je tačno greška koju spec opisuje kod Performance API-ja.
            self.unmeasured += 1
            return

        kind = _resource_type(response)
        self.total_bytes += size
        self.by_type[kind] = self.by_type.get(kind, 0) + size
        self.bytes_by_url[url] = size

    async def drain(self, timeout: float) -> None:
        """Telo koje ne stigne za `timeout` je nemereno, ne nula.

        Strim ili video se ne završi nikad, a `response.body()` na njega čeka bez
        kraja — na protetica.com je to zauvek blokiralo ceo prolaz.
        """
        if self._tasks:
            _done, pending = await asyncio.wait(self._tasks, timeout=timeout)
            for task in pending:
                task.cancel()
                self.unmeasured += 1
            self._tasks.clear()


def _resource_type(response: Any) -> str:
    try:
        kind = response.request.resource_type
    except Exception:  # noqa: BLE001
        return "other"
    return kind if kind in {"image", "script", "stylesheet", "document", "font", "media"} else "other"


def est_waste_kb(transfer_bytes: int, natural: Sequence[int], client: Sequence[int]) -> float:
    """§7.5: grubo, ali daje broj koji možeš da napišeš u mejlu."""
    natural_area = natural[0] * natural[1]
    if not transfer_bytes or natural_area <= 0:
        return 0.0
    used = (client[0] * client[1] * 4) / natural_area
    return round(max(transfer_bytes / 1024 * (1 - used), 0.0), 1)


class _LoadSlot:
    """Isključivo pravo na učitavanje do `load` (BUG-006).

    Tri sajta koja se učitavaju istovremeno dele istu vezu i produžavaju jedan
    drugom vreme učitavanja do 4,6×. Zato se učitava jedan po jedan; skrol, DOM i
    merenje težine i dalje idu paralelno. Oslobađa se tačno jednom, ma kako se
    merenje završilo.
    """

    def __init__(self, lock: asyncio.Lock | None) -> None:
        self._lock = lock
        self._held = False

    async def acquire(self) -> None:
        if self._lock is not None:
            await self._lock.acquire()
            self._held = True

    def release(self) -> None:
        if self._held:
            self._held = False
            self._lock.release()


async def capture(
    browser: Any, site: SiteSnapshot, config: dict, slot: _LoadSlot | None = None
) -> BrowserSnapshot:
    """Nov kontekst po domenu = prazan keš.

    Bez toga drugi domen sa istog CDN-a meri lažno manju težinu (§15, zamka 10).
    `slot` se oslobađa čim se stranica učita, pa sledeći sajt meri svoje vreme bez
    tuđeg saobraćaja na vezi.
    """
    from playwright.async_api import Error as PlaywrightError

    url = (site.home.final_url if site.home else None) or (
        site.entry.final_url if site.entry else f"https://{site.domain}/"
    )
    snapshot = BrowserSnapshot(
        domain=site.domain,
        url=url,
        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        scanner_version=__version__,
    )
    timeout_ms = get(config, "browser.timeout_s") * 1000
    recorder = _Recorder()
    context = await browser.new_context(
        viewport={
            "width": get(config, "browser.viewport_width"),
            "height": get(config, "browser.viewport_height"),
        },
        device_scale_factor=1,
        user_agent=user_agent(config),
        ignore_https_errors=True,  # nevalidan sertifikat je nalaz nivoa 1, ne razlog da nivo 2 stane
    )
    try:
        page = await context.new_page()
        page.on("request", recorder.on_request)
        page.on("response", recorder.on_response)
        page.on("console", recorder.on_console)
        page.on("pageerror", recorder.on_page_error)

        reached = "error"
        try:
            await page.goto(url, wait_until="load", timeout=timeout_ms)
            reached = "load"
        except PlaywrightError as exc:
            if "Timeout" not in type(exc).__name__ and "imeout" not in str(exc):
                snapshot.errors.append(SnapshotError("goto", type(exc).__name__, str(exc)[:300]))
                snapshot.status = "failed"
                return snapshot
            reached = "timeout"

        if reached == "load":
            # Mirovanje mreže je poželjno, ne obavezno.
            with contextlib.suppress(PlaywrightError):
                await page.wait_for_load_state(
                    "networkidle", timeout=get(config, "browser.idle_after_load_ms")
                )
        if slot is not None:
            slot.release()

        # Bez skrola sve lazy slike imaju naturalWidth == 0 i provera tiho nalazi
        # nulu (§15, zamka 2).
        try:
            await page.evaluate(_SCROLL)
            await page.wait_for_timeout(get(config, "browser.scroll_pause_ms"))
        except PlaywrightError as exc:
            snapshot.errors.append(SnapshotError("scroll", type(exc).__name__, str(exc)[:200]))

        await recorder.drain(get(config, "browser.drain_timeout_s"))
        snapshot.timing = await _read_timing(page, reached, PlaywrightError)
        snapshot.dom = await _read_dom(page, recorder, config, PlaywrightError, snapshot)
        snapshot.network = NetworkStats(
            request_count=recorder.request_count,
            total_bytes=recorder.total_bytes,
            bytes_by_type=recorder.by_type,
            unmeasured_responses=recorder.unmeasured,
        )
        snapshot.console = ConsoleStats(
            errors=recorder.console_errors,
            warnings=recorder.console_warnings,
            samples=recorder.samples,
        )
        snapshot.status = "ok" if reached == "load" else "partial"
    except Exception as exc:  # noqa: BLE001 — izuzetak nikad ne napušta domen (§8.2)
        snapshot.errors.append(SnapshotError("browser", type(exc).__name__, str(exc)[:300]))
        snapshot.status = "failed"
    finally:
        if slot is not None:
            slot.release()
        # I zatvaranje ume da zaglavi; posle tvrdog limita ne sme da ga produži.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(context.close(), CLOSE_TIMEOUT_S)
    return snapshot


async def _read_timing(page: Any, reached: str, error_type: type) -> TimingStats:
    try:
        raw = await page.evaluate(_TIMING)
    except error_type:
        raw = None
    if not raw:
        return TimingStats(reached=reached)
    return TimingStats(
        dom_content_loaded_ms=raw.get("dcl"),
        load_ms=raw.get("load") if reached == "load" else None,
        reached=reached,
    )


async def _read_dom(
    page: Any, recorder: _Recorder, config: dict, error_type: type, snapshot: BrowserSnapshot
) -> DomStats:
    try:
        raw = await page.evaluate(_DOM, get(config, "thresholds.perf.image_ratio"))
    except error_type as exc:
        snapshot.errors.append(SnapshotError("dom", type(exc).__name__, str(exc)[:200]))
        return DomStats()

    oversized = [
        OversizedImage(
            src=item["src"],
            natural=[item["nw"], item["nh"]],
            client=[item["cw"], item["ch"]],
            ratio=round(item["ratio"], 2),
            est_waste_kb=est_waste_kb(
                recorder.bytes_by_url.get(item["src"], 0),
                [item["nw"], item["nh"]],
                [item["cw"], item["ch"]],
            ),
        )
        for item in raw["oversized"]
    ]
    oversized.sort(key=lambda image: -image.est_waste_kb)
    return DomStats(
        h1_count=raw["h1"],
        images_total=raw["total"],
        images_without_alt_attr=raw["withoutAlt"],
        images_empty_alt=raw["emptyAlt"],
        oversized_images=oversized,
        images_unmeasured=raw["unmeasured"],
    )


async def _capture_within_limit(
    browser: Any, site: SiteSnapshot, config: dict, load_lock: asyncio.Lock | None = None
) -> BrowserSnapshot:
    """Tvrd limit po domenu — poslednja odbrana od zastoja za koji još ne znamo.

    Jedan domen koji visi ne sme da zaustavi ostalih 199 (§8.2). Čekanje na red za
    učitavanje nije rad na domenu, pa ne ulazi u limit.
    """
    limit_s = get(config, "browser.max_seconds_per_domain")
    slot = _LoadSlot(load_lock)
    await slot.acquire()
    try:
        return await asyncio.wait_for(capture(browser, site, config, slot), limit_s)
    except TimeoutError:
        log.error("nivo 2 prekinut posle %s s", limit_s, extra={"domain": site.domain})
        return BrowserSnapshot(
            domain=site.domain,
            url=(site.home.final_url if site.home else None) or "",
            fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            status="failed",
            errors=[SnapshotError("browser", "timeout", f"prekinut posle tvrdog limita od {limit_s} s")],
        )
    finally:
        slot.release()


def _tiho_za_zatvoren_kontekst(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Posle tvrdog limita Playwright-ova navigacija ostane bez čitaoca; kad se kontekst
    zatvori, njena greška je očekivana posledica prekida, ne kvar (BUG-007). Sve ostalo
    ide dalje kao i do sada.
    """
    if type(context.get("exception")).__name__ == "TargetClosedError":
        return
    loop.default_exception_handler(context)


def _launch_options(config: dict) -> dict[str, Any]:
    """Gotov Chromium umesto Playwright-ovog, kad ga okruženje već ima."""
    path = get(config, "browser.executable_path") or os.environ.get("SKENER_CHROMIUM", "")
    return {"executable_path": path} if path else {}


async def capture_all(
    sites: Iterable[SiteSnapshot], config: dict, snapshot_dir: Path | None = None
) -> dict[str, BrowserSnapshot]:
    """Jedna instanca browsera za ceo prolaz, nov kontekst po domenu (§7.1)."""
    from playwright.async_api import async_playwright

    sites = list(sites)
    if not sites:
        return {}

    results: dict[str, BrowserSnapshot] = {}
    # Nivo 2 ide na 3 istovremena konteksta, ne 8: svaki je stotine MB RAM-a (§8.1).
    limit = asyncio.Semaphore(get(config, "browser.concurrency"))
    # Učitava se jedan po jedan; ostatak merenja ide paralelno (BUG-006).
    load_lock = asyncio.Lock()
    # Petlja pripada ovom prolazu (`asyncio.run` po nivou), pa se rukovalac ne vraća:
    # zaostale greške stižu i posle povratka, kad ih sakupljač smeća pokupi.
    asyncio.get_running_loop().set_exception_handler(_tiho_za_zatvoren_kontekst)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_launch_options(config))
        try:

            async def one(site: SiteSnapshot) -> tuple[str, BrowserSnapshot]:
                async with limit:
                    log.info("nivo 2 počinje", extra={"domain": site.domain})
                    snapshot = await _capture_within_limit(browser, site, config, load_lock)
                    if snapshot_dir is not None:
                        store.write_browser(snapshot_dir, snapshot)
                    log.info(
                        "nivo 2 gotov: %d B u %d zahteva (%s)",
                        snapshot.network.total_bytes,
                        snapshot.network.request_count,
                        snapshot.timing.reached,
                        extra={"domain": site.domain},
                    )
                    return site.domain, snapshot

            gathered = await asyncio.gather(*(one(s) for s in sites), return_exceptions=True)
        finally:
            await browser.close()

    for site, item in zip(sites, gathered, strict=True):
        if isinstance(item, BaseException):
            log.error("nivo 2 izgubljen: %r", item, extra={"domain": site.domain})
            results[site.domain] = BrowserSnapshot(
                domain=site.domain,
                errors=[SnapshotError("browser", type(item).__name__, str(item)[:300])],
            )
        else:
            results[item[0]] = item[1]
    return results
