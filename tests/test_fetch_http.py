"""Integracioni testovi fetchera nivoa 1 protiv lokalnog servera.

Bez mreže ka spolja, ali sa pravim `httpx`-om, pravim semaforima i pravim
budžetom — jedino tako se §4.2, §4.6 i §8 zaista proveravaju.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from factories import run_level
from localserver import FakeSite, Response, html

from skener import store
from skener.config import load_config
from skener.fetch.http import (
    DomainBudget,
    Fetcher,
    Outcome,
    _classify,
    _should_retry,
    fetch_site,
    probe_urls,
    scan_domains,
)
from skener.models import DomainInput


def scan(site: FakeSite, **config_overrides) -> object:
    """Pauze su podrazumevano nula; test pristojnosti ih izričito uključuje."""
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    for dotted, value in config_overrides.items():
        section, _, key = dotted.rpartition(".")
        node = cfg
        for part in section.split("."):
            node = node[part]
        node[key] = value

    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url, industry="ostalo"))

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# Pun prolaz
# --------------------------------------------------------------------------- #
def test_pun_prolaz_sklapa_snapshot():
    with FakeSite() as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert snapshot.robots.status == 200
    assert snapshot.sitemap.status == 200
    assert snapshot.sample_source == "sitemap"
    assert snapshot.home.title == "Početna"
    assert snapshot.home.raw_html, "sirovi HTML početne je potreban za eskalaciju i debug"
    assert all(p.raw_html is None for p in snapshot.pages[1:]), "sirovi HTML samo za početnu (§3.2)"
    assert len(snapshot.pages) >= 4
    assert len(snapshot.soft404.probes) == 2
    assert all(p.status == 404 for p in snapshot.soft404.probes)


def test_cist_lokalni_sajt_daje_malo_nalaza():
    """Kontrola protiv lažnih pozitiva nad sajtom koji je namerno uredan (U4)."""
    with FakeSite() as site:
        snapshot = scan(site)
    nalazi = {cid for cid, r in run_level(1, snapshot).items() if r.status == "finding"}
    assert nalazi <= {"infra.sitemap.missing"} or nalazi == set(), f"neočekivani nalazi: {nalazi}"


def test_rekurzija_kroz_sitemapindex():
    with FakeSite() as site:
        snapshot = scan(site)
    assert snapshot.sitemap.nested_count == 1
    assert snapshot.sitemap.depth_reached == 1
    assert any(url.endswith("/usluge") for url in snapshot.sitemap.urls)


def test_robots_disallow_se_postuje():
    """Sitemap nudi /tajno/nesto; alat koji ga ipak traži je nekonzistentan (§4.3)."""
    with FakeSite() as site:
        snapshot = scan(site)
        trazeno = site.paths()
    assert any("/tajno/nesto" in url for url in snapshot.sitemap.urls), "sitemap ga jeste nudio"
    assert not any(path.startswith("/tajno") for path in trazeno), f"tražene putanje: {trazeno}"


def test_sitemap_direktiva_iz_robots_a_ima_prednost():
    with FakeSite() as site:
        scan(site)
        trazeno = site.paths()
    assert "/sitemap.xml" in trazeno


def test_sonde_su_deterministicke():
    """Isti domen mora da da iste sonde u svakom prolazu, inače testovi ne važe (§5.2)."""
    prvi = probe_urls("mensa.rs", "https://mensa.rs/")
    assert prvi == probe_urls("mensa.rs", "https://mensa.rs/")
    assert prvi != probe_urls("angolo.rs", "https://angolo.rs/")
    assert prvi[0].endswith("9e906fa852dc56e1") and prvi[1].endswith(".html")


def test_sonde_u_snapshotu_prate_cistu_funkciju():
    with FakeSite() as site:
        snapshot = scan(site)
        ocekivano = probe_urls(site.base_url, site.base_url)
    assert [p.url for p in snapshot.soft404.probes] == ocekivano


# --------------------------------------------------------------------------- #
# Pristojnost i konkurentnost (§8)
# --------------------------------------------------------------------------- #
def test_nikad_dva_paralelna_zahteva_ka_istom_hostu():
    """Po-hostu semafor je granica između alata i napada (§8.1)."""
    with FakeSite() as site:
        scan(site)
        assert site.concurrent_peak == 1, f"paralelnih ka istom hostu: {site.concurrent_peak}"


def test_pauza_izmedju_zahteva_ka_istom_hostu():
    with FakeSite() as site:
        import time

        started = time.monotonic()
        scan(site, **{"http.delay_ms": [120, 120], "http.max_requests_per_domain": 5})
        elapsed = time.monotonic() - started
    assert elapsed >= 0.4, f"pauze nisu ispoštovane, prolaz je trajao {elapsed:.2f} s"


def test_vise_domena_ide_paralelno():
    with FakeSite() as a, FakeSite() as b, FakeSite() as c:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=s.base_url) for s in (a, b, c)]
        snapshots = asyncio.run(scan_domains(targets, cfg))
    assert len(snapshots) == 3
    assert all(s.entry.status == 200 for s in snapshots)


# --------------------------------------------------------------------------- #
# Budžet (§4.2)
# --------------------------------------------------------------------------- #
def test_budzet_zaustavlja_prolaz_a_ne_ruši_ga():
    with FakeSite() as site:
        snapshot = scan(site, **{"http.max_requests_per_domain": 3, "http.delay_ms": [0, 0]})
        trazeno = len(site.paths())

    assert trazeno <= 3, f"budžet probijen: {trazeno} zahteva"
    assert snapshot.budget.exhausted
    assert "budžet" in snapshot.budget.aborted_reason
    # Ono što je prikupljeno ide dalje, ostalo je `unknown` — ne pad.
    assert snapshot.entry.status == 200
    rezultati = run_level(1, snapshot)
    assert len(rezultati) == 20
    assert all(r.reason for r in rezultati.values() if r.status == "unknown")


def test_budzet_broji_i_vreme():
    budget = DomainBudget(max_requests=100, max_seconds=0)
    assert budget.take() is False
    assert "s" in budget.aborted_reason


# --------------------------------------------------------------------------- #
# Greške, ponovni pokušaji, odustajanje (§4.6, §8.3)
# --------------------------------------------------------------------------- #
def test_petsto_se_ponavlja_jednom_i_uspeva():
    pokusaji = {"broj": 0}

    def flaky() -> Response:
        pokusaji["broj"] += 1
        if pokusaji["broj"] == 1:
            return Response(b"greska", status=500)
        return Response(html("Usluge"))

    with FakeSite(extra={"/usluge": flaky}) as site:
        snapshot = scan(site)

    usluge = [p for p in snapshot.pages if p.url.endswith("/usluge")]
    assert pokusaji["broj"] == 2, "5xx se ponavlja tačno jednom (§4.6)"
    assert usluge and usluge[0].status == 200


def test_cetiristo_se_ne_ponavlja():
    pokusaji = {"broj": 0}

    def not_found() -> Response:
        pokusaji["broj"] += 1
        return Response(b"nema", status=404)

    with FakeSite(extra={"/usluge": not_found}) as site:
        scan(site)
    assert pokusaji["broj"] == 1, "4xx je odgovor, ne greška (§4.6)"


def test_na_429_se_odustaje_od_domena():
    with FakeSite(extra={"/robots.txt": Response(b"stani", status=429)}) as site:
        snapshot = scan(site)
        trazeno = site.paths()

    assert "429" in snapshot.budget.aborted_reason
    assert trazeno.count("/robots.txt") == 1, "na 429 se ne pokušava ponovo (§8.3)"
    assert len(trazeno) == 2, f"posle 429 nema daljih zahteva, a bilo ih je: {trazeno}"


def test_lazni_404_se_prepoznaje_kroz_ceo_lanac():
    with FakeSite(soft404=True) as site:
        snapshot = scan(site)

    assert all(p.status == 200 for p in snapshot.soft404.probes)
    result = run_level(1, snapshot)["infra.soft404"]
    assert result.status == "finding"
    assert result.findings[0].evidence["tvrd_dokaz"] is True


def test_preusmerenja_se_belezе():
    with FakeSite(
        extra={
            "/": Response(b"", status=301, headers={"Location": "/korak1"}),
            "/korak1": Response(b"", status=301, headers={"Location": "/korak2"}),
            "/korak2": Response(b"", status=301, headers={"Location": "/kraj"}),
            "/kraj": Response(html("Kraj")),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.entry.status == 200
    assert len(snapshot.entry.redirect_chain) == 4
    assert run_level(1, snapshot)["perf.redirect.chain"].status == "finding"


def test_kompresovan_odgovor_ne_pali_nalaz():
    with FakeSite(
        extra={"/": Response(html("Početna", body="x" * 80_000), headers={"content-encoding": "gzip"})}
    ) as site:
        snapshot = scan(site)
    assert snapshot.home.headers.get("content-encoding") == "gzip"
    assert run_level(1, snapshot)["perf.compression.missing"].status == "ok"


def test_nekompresovan_veliki_html_pali_nalaz():
    with FakeSite(extra={"/": Response(html("Početna", body="x" * 80_000))}) as site:
        snapshot = scan(site)
    assert run_level(1, snapshot)["perf.compression.missing"].status == "finding"


def test_fallback_na_interne_linkove_kad_nema_sitemapa():
    with FakeSite(
        extra={
            "/sitemap.xml": Response(b"nema", status=404),
            "/robots.txt": Response(b"nema", status=404),
        }
    ) as site:
        snapshot = scan(site)

    assert snapshot.sample_source == "links"
    assert any(p.url.endswith("/usluge") for p in snapshot.pages)
    assert run_level(1, snapshot)["infra.sitemap.missing"].status == "finding"
    assert run_level(1, snapshot)["infra.robots.missing"].status == "finding"


# --------------------------------------------------------------------------- #
# Klasifikacija izuzetaka — jedini deo §4.6 koji se ne može izazvati lokalno
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc, expected",
    [
        (httpx.ConnectError("x", request=None), "connection"),
        (httpx.ConnectTimeout("x", request=None), "connect_timeout"),
        (httpx.ReadTimeout("x", request=None), "read_timeout"),
        (httpx.TooManyRedirects("x", request=None), "too_many_redirects"),
    ],
)
def test_klasifikacija_izuzetaka(exc, expected):
    assert _classify(exc)[0] == expected


def test_dns_greska_se_prepoznaje_kroz_lanac_uzroka():
    try:
        try:
            raise socket.gaierror(-2, "Name or service not known")
        except socket.gaierror as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "dns"


def test_istekao_sertifikat_je_tls_a_ne_pad():
    import ssl

    try:
        try:
            raise ssl.SSLCertVerificationError("certificate has expired")
        except ssl.SSLCertVerificationError as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == "tls"


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (Outcome(url="u", status=404), False),
        (Outcome(url="u", status=500), True),
        (Outcome(url="u", status=200), False),
        (Outcome(url="u", error_kind="read_timeout"), True),
        (Outcome(url="u", error_kind="dns"), False),
        (Outcome(url="u", error_kind="tls"), False),
    ],
)
def test_politika_ponovnih_pokusaja(outcome, expected):
    assert _should_retry(outcome) is expected


def test_pokvaren_domen_ne_ruši_prolaz():
    """Ubacivanje namerno pokvarenog domena ne sme da obori ceo prolaz (§13, faza 3)."""
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        cfg["http"]["timeout_connect_s"] = 1
        targets = [
            DomainInput(domain=site.base_url),
            DomainInput(domain="http://127.0.0.1:1"),  # niko ne sluša
        ]
        snapshots = asyncio.run(scan_domains(targets, cfg))

    assert len(snapshots) == 2
    assert snapshots[0].entry.status == 200
    assert snapshots[1].entry.status is None
    assert run_level(1, snapshots[1]) and len(run_level(1, snapshots[1])) == 20


def test_snapshot_se_pise_na_disk_cim_je_domen_gotov(tmp_path):
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        asyncio.run(scan_domains([DomainInput(domain=site.base_url)], cfg, snapshot_dir=tmp_path))

    zapisani = list(tmp_path.glob("*/site.json"))
    assert len(zapisani) == 1, f"nije zapisano: {list(tmp_path.rglob('*'))}"
    ucitani = list(store.read_all(tmp_path))
    assert len(ucitani) == 1 and ucitani[0][0].entry.status == 200


@pytest.mark.parametrize(
    "domain, expected",
    [
        ("mensa.rs", "mensa.rs"),
        ("http://127.0.0.1:8123", "http_127.0.0.1_8123"),
        ("../../etc/passwd", "etc_passwd"),
        ("", "nepoznat-domen"),
    ],
)
def test_ime_direktorijuma_ne_izlazi_iz_izlaznog_foldera(domain, expected):
    """Domen dolazi iz korisnikovog CSV-a — granica poverenja."""
    assert store.slug(domain) == expected
