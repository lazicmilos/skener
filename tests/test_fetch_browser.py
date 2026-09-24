"""Nivo 2 protiv lokalnog servera i pravog Chromiuma (§7).

Označeno `browser`: preskače se ako Playwright ili Chromium nisu instalirani.
"""

from __future__ import annotations

import asyncio
import struct
import zlib

import pytest
from factories import run_level
from localserver import FakeSite, Response

from skener.config import load_config
from skener.fetch.browser import est_waste_kb
from skener.models import Entry, PageSnapshot, SiteSnapshot

playwright_api = pytest.importorskip("playwright.async_api", reason="Playwright nije instaliran")
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module", autouse=True)
def chromium_se_pokrece():
    """Uvoz nije dovoljan: paket bez odgovarajućeg Chromium-a puca tek na `launch`.

    Tipično posle nadogradnje Playwright-a bez `playwright install` — to je stanje
    okruženja, ne greška u alatu, pa je preskakanje, a ne deset crvenih testova.
    """
    from skener.fetch.browser import _launch_options

    async def probaj() -> None:
        async with playwright_api.async_playwright() as pw:
            browser = await pw.chromium.launch(**_launch_options(load_config()))
            await browser.close()

    try:
        asyncio.run(probaj())
    except playwright_api.Error as exc:
        razlog = str(exc).splitlines()[0]
        pytest.skip(f"Chromium se ne pokreće ({razlog}); pokreni `playwright install chromium`")


def png(width: int, height: int) -> bytes:
    """Minimalan validan PNG — da `naturalWidth` bude stvaran, bez nove zavisnosti."""
    raw = b"".join(b"\x00" + b"\xc8\x32\x32" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


TESKA_STRANA = """<!doctype html><html lang="sr"><head><title>Teška strana</title>
<style>img{{width:100px}} .daleko{{margin-top:4000px}}</style></head>
<body>
  <h2>Nema h1 na ovoj strani</h2>
  <img src="/velika.png">
  <img src="/velika.png" alt="">
  <img src="/velika.png" alt="opisana slika">
  {bez_alta}
  <div class="daleko"><img src="/lenja.png" loading="lazy"></div>
  <script src="/tezak.js"></script>
  <script>null.x = 1;</script>
  <script>undefined.y = 2;</script>
  <script>console.error("prva"); console.error("druga"); console.warn("upozorenje");</script>
</body></html>"""


def teski_sajt() -> FakeSite:
    bez_alta = "".join('<img src="/velika.png">' for _ in range(7))
    return FakeSite(
        extra={
            "/": Response(TESKA_STRANA.format(bez_alta=bez_alta).encode()),
            "/velika.png": Response(png(800, 600), headers={"content-type": "image/png"}),
            "/lenja.png": Response(png(900, 600), headers={"content-type": "image/png"}),
            "/tezak.js": Response(
                b"window.__x = '" + b"y" * 300_000 + b"';",
                headers={"content-type": "application/javascript"},
            ),
        }
    )


def snimi(site: FakeSite, config: dict | None = None):
    from skener.fetch.browser import capture_all

    fake = SiteSnapshot(
        domain=site.base_url,
        pages=[PageSnapshot(url=site.base_url + "/", final_url=site.base_url + "/", status=200)],
        entry=Entry(requested_url=site.base_url + "/", final_url=site.base_url + "/", status=200),
    )
    return asyncio.run(capture_all([fake], config or load_config()))[site.base_url]


@pytest.fixture(scope="module")
def snimak():
    with teski_sajt() as site:
        yield snimi(site)


# --------------------------------------------------------------------------- #
# Merenje težine (§7.2) — najozbiljnija zamka u projektu
# --------------------------------------------------------------------------- #
def test_tezina_se_meri_iz_mreznog_saobracaja(snimak):
    """Performance API bi ovde vratio skoro nulu za resurse sa drugog porekla."""
    assert snimak.status == "ok"
    assert snimak.network.total_bytes > 300_000, "skripta od 300 kB mora da se vidi u zbiru"
    # Deset `<img>` sa istim URL-om je jedan zahtev — browser ih sam sažima.
    assert snimak.network.request_count >= 4
    assert snimak.network.bytes_by_type.get("script", 0) > 250_000
    assert snimak.network.bytes_by_type.get("image", 0) > 0


def test_nemereni_odgovori_se_broje_a_ne_prećutkuju(snimak):
    assert snimak.network.unmeasured_responses == 0


def test_preusmerenja_se_ne_broje_kao_nemerena():
    with FakeSite(
        extra={
            "/": Response(b"", status=302, headers={"Location": "/kraj"}),
            "/kraj": Response(b"<html><h1>Kraj</h1></html>"),
        }
    ) as site:
        snimak = snimi(site)
    assert snimak.network.unmeasured_responses == 0
    assert snimak.dom.h1_count == 1


def test_timing_se_belezi(snimak):
    assert snimak.timing.reached == "load"
    assert snimak.timing.load_ms is not None and snimak.timing.load_ms > 0


# --------------------------------------------------------------------------- #
# DOM (§7.4, §7.5)
# --------------------------------------------------------------------------- #
def test_h1_se_broji_iz_nacrtane_strane(snimak):
    assert snimak.dom.h1_count == 0
    assert run_level(2, snimak)["seo.h1.missing"].status == "finding"


def test_alt_stanja_se_broje_odvojeno(snimak):
    """Tri stanja, ne dva (§7.4)."""
    assert snimak.dom.images_total == 11
    assert snimak.dom.images_without_alt_attr == 9
    assert snimak.dom.images_empty_alt == 1


def test_lenja_slika_se_meri_jer_se_skroluje_do_dna(snimak):
    """Bez skrola bi imala naturalWidth == 0 i tiho ispala iz merenja (§15, zamka 2)."""
    assert snimak.dom.images_unmeasured == 0
    assert any("lenja.png" in image.src for image in snimak.dom.oversized_images)


def test_predimenzionirane_slike_sa_procenjenim_viskom(snimak):
    assert len(snimak.dom.oversized_images) >= 4
    najgora = snimak.dom.oversized_images[0]
    assert najgora.ratio > 2.5
    assert najgora.natural[0] in (800, 900) and najgora.client[0] == 100
    assert najgora.est_waste_kb > 0
    assert run_level(2, snimak)["perf.img.oversized"].status == "finding"


def test_console_greske_se_broje(snimak):
    assert snimak.console.errors >= 4  # dva pageerror-a i dva console.error
    assert snimak.console.warnings >= 1
    assert snimak.console.samples


# --------------------------------------------------------------------------- #
# Prazan keš po domenu (§15, zamka 10)
# --------------------------------------------------------------------------- #
def test_drugi_prolaz_meri_isto_jer_je_kes_prazan():
    """Nov kontekst po domenu; inače drugi sajt sa istog CDN-a ispadne lakši."""
    with teski_sajt() as site:
        prvi = snimi(site)
        drugi = snimi(site)
    assert drugi.network.total_bytes == pytest.approx(prvi.network.total_bytes, rel=0.02)
    assert drugi.network.unmeasured_responses == 0


# --------------------------------------------------------------------------- #
# Zastoji — snimljeno na protetica.com: jedan odgovor čije telo nikad ne stigne
# je zauvek blokirao ceo prolaz. Sve ovde mora da se završi u roku.
# --------------------------------------------------------------------------- #
STRIM_STRANA = b"""<!doctype html><html lang="sr"><head><title>Strim</title></head>
<body><h1>Strana sa strimom</h1><script>fetch('/strim').then(r => r.text())</script></body></html>"""


def test_telo_koje_ne_stigne_je_nemereno_a_ne_zastoj():
    """Strim ili video koji se ne završi: `load` stigne, telo odgovora nikad."""
    import time

    cfg = load_config()
    cfg["browser"]["drain_timeout_s"] = 2
    with FakeSite(
        extra={
            "/": Response(STRIM_STRANA),
            "/strim": Response(b"x" * 10_000, headers={"content-type": "text/plain"}, stall=120),
        }
    ) as site:
        started = time.monotonic()
        snimak = snimi(site, cfg)
        trajanje = time.monotonic() - started

    assert trajanje < 20, f"nivo 2 je čekao telo strima {trajanje:.0f} s"
    assert snimak.status == "ok"
    assert snimak.dom.h1_count == 1, "ostatak merenja mora da preživi"
    assert snimak.network.unmeasured_responses >= 1, "strim je nemeren, ne nula bajtova"


def test_tvrdi_limit_po_domenu_prekida_nivo_2():
    """Poslednja odbrana: bilo koji zastoj koji još ne znamo ne sme da zaustavi prolaz."""
    import time

    cfg = load_config()
    cfg["browser"]["max_seconds_per_domain"] = 3
    with FakeSite(
        extra={
            "/": Response(b"<html><h1>Spora</h1><img src='/spora.png'></html>"),
            "/spora.png": Response(png(10, 10), headers={"content-type": "image/png"}, delay=30),
        }
    ) as site:
        started = time.monotonic()
        snimak = snimi(site, cfg)
        trajanje = time.monotonic() - started

    assert trajanje < 15, f"tvrdi limit od 3 s nije poštovan: {trajanje:.0f} s"
    assert snimak.status == "failed"
    assert any("tvrdog limita" in e.detail for e in snimak.errors), snimak.errors


# --------------------------------------------------------------------------- #
# Formula za procenu viška (§7.5) — čista funkcija, bez browsera
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "transfer_kb, natural, client, expected",
    [
        (2150, [4000, 2667], [760, 507], 1838.0),  # primer iz §3.3: ≈ 1840 kB
        (100, [100, 100], [100, 100], 0.0),  # slika tačne veličine nema višak
        (0, [4000, 2667], [760, 507], 0.0),  # bez izmerenog prenosa nema procene
    ],
)
def test_procena_viska(transfer_kb, natural, client, expected):
    assert est_waste_kb(transfer_kb * 1024, natural, client) == pytest.approx(expected, abs=2.0)


def test_neizmerena_slika_ne_daje_negativan_visak():
    assert est_waste_kb(1000, [10, 10], [500, 500]) == 0.0
