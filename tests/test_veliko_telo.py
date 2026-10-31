"""Granica na telo odgovora: gzip bomba i preveliko telo ne smeju da pojedu memoriju.

Skenirani sajt je nepoverljiv ulaz. Odgovor od par kB sa `Content-Encoding: gzip` ili mapa
sajta `.xml.gz` raspakuju se u gigabajte, pa granica mora da važi *dok* se raspakuje, a ne
posle. Oznake slučajeva kao u `test_granice.py`: `gv-` granična vrednost, `ke-` klasa
ekvivalencije.
"""

from __future__ import annotations

import asyncio
import gzip
import struct
import tracemalloc
import zlib

import pytest
from factories import run_level
from localserver import FakeSite, Response, html

from skener import score
from skener.checks import registry
from skener.config import load_config
from skener.fetch import sitemap
from skener.fetch.http import PREVELIKO, Fetcher, fetch_site
from skener.messages import reason
from skener.models import DomainInput

MIB = 1024 * 1024
URLSET = b'<?xml version="1.0"?><urlset><url><loc>https://d.rs/usluge</loc></url></urlset>'


def bomba(decoded_bytes: int) -> bytes:
    """gzip od `decoded_bytes` nula, sastavljen u komadima: test sam ne drži celu bombu u memoriji."""
    packer = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
    komad = bytes(MIB)
    out = [packer.compress(komad) for _ in range(decoded_bytes // MIB)]
    return b"".join(out) + packer.flush()


def prazni_blokovi(n: int) -> bytes:
    """Ispravan gzip od `<html></html>` sa `n` praznih deflate blokova po 5 B: mnogo sirovih
    bajtova koji se raspakuju u ništa."""
    telo = b"<html></html>"
    packer = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    deflate = packer.compress(telo) + packer.flush(zlib.Z_SYNC_FLUSH)
    deflate += b"\x00\x00\x00\xff\xff" * n + b"\x03\x00"
    zaglavlje = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    return zaglavlje + deflate + struct.pack("<II", zlib.crc32(telo), len(telo))


def html_od(n: int) -> bytes:
    """HTML od tačno `n` bajtova (posle raspakivanja)."""
    osnova = html("Velika")
    assert len(osnova) <= n
    return osnova.replace(b"</body>", b" " * (n - len(osnova)) + b"</body>")


def config(**overrides):
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    for dotted, value in overrides.items():
        *put, kljuc = dotted.split("__")
        node = cfg
        for deo in put:
            node = node[deo]
        node[kljuc] = value
    return cfg


def scan(site: FakeSite, cfg: dict):
    async def run():
        async with Fetcher(cfg) as fetcher:
            return await fetch_site(fetcher, DomainInput(domain=site.base_url, industry="ostalo"))

    return asyncio.run(run())


def vrh_memorije(fn):
    """(rezultat, najveća zauzeta memorija u bajtovima) — i u niti lažnog servera."""
    tracemalloc.start()
    try:
        rezultat = fn()
        return rezultat, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# --------------------------------------------------------------------------- #
# Mapa sajta: `.xml.gz` se raspakuje najviše do MAX_PARSE_BYTES + 1
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "pomak, vrsta",
    [
        pytest.param(-1, "urlset", id="gv-10MiB-minus"),
        pytest.param(0, "urlset", id="gv-10MiB"),
        pytest.param(1, "unknown", id="gv-10MiB-plus"),
    ],
)
def test_granica_raspakovane_mape(pomak, vrsta):
    """Razmak posle korenskog elementa je ispravan XML, pa veličina ne menja sadržaj."""
    n = sitemap.MAX_PARSE_BYTES + pomak
    data = gzip.compress(URLSET + b" " * (n - len(URLSET)))
    assert sitemap.parse(data)[0] == vrsta


def test_gzip_bomba_kao_mapa_ne_raspakuje_se_do_kraja():
    """100 MiB nula u ~100 kB: `gzip.decompress` je pre provere dužine zauzeo svih 100 MiB."""
    data = bomba(100 * MIB)
    assert len(data) < MIB

    rezultat, vrh = vrh_memorije(lambda: sitemap.parse(data))

    assert rezultat == ("unknown", [])
    assert vrh < 3 * sitemap.MAX_PARSE_BYTES, f"zauzeto {vrh / MIB:.0f} MiB"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(gzip.compress(URLSET)[:-12], id="ke-odsecen"),
        pytest.param(gzip.compress(URLSET)[:10] + b"\xff" * 20, id="ke-pokvaren-deflate"),
    ],
)
def test_ostecen_gzip_je_unknown_a_ne_izuzetak(data):
    """`gzip.decompress` je bacao `EOFError` i `zlib.error`, a hvatao se samo `OSError`."""
    assert sitemap.parse(data) == ("unknown", [])


def test_gzip_bomba_kao_mapa_na_sajtu_ne_obara_prolaz():
    """Mapa koja se ne može pročitati daje `infra.sitemap.missing`, kao i ranije; uzorak ide iz veza."""
    mapa = Response(bomba(64 * MIB), headers={"content-type": "application/x-gzip"})
    with FakeSite(extra={"/sitemap.xml": mapa}) as site:
        snapshot, vrh = vrh_memorije(lambda: scan(site, config()))

    assert snapshot.sitemap.status == 200
    assert snapshot.sitemap.urls == []
    assert snapshot.sample_source == "links"
    assert run_level(1, snapshot)["infra.sitemap.missing"].status == "finding"
    assert vrh < 3 * sitemap.MAX_PARSE_BYTES, f"zauzeto {vrh / MIB:.0f} MiB"


def test_mapa_veca_od_granice_tela_je_kao_neispravna_mapa():
    """Preko `http.max_body_bytes` mapa se ne čita do kraja; status ostaje 200, kao kod prevelike mape."""
    velika = URLSET + b" " * 70_000
    mapa = Response(velika, headers={"content-type": "application/xml", "content-encoding": "gzip"})
    with FakeSite(extra={"/sitemap.xml": mapa}) as site:
        snapshot = scan(site, config(http__max_body_bytes=64 * 1024))

    assert snapshot.sitemap.status == 200
    assert snapshot.sitemap.urls == []
    assert run_level(1, snapshot)["infra.sitemap.missing"].status == "finding"


# --------------------------------------------------------------------------- #
# Stranica: telo preko `http.max_body_bytes` je `body_too_large`
# --------------------------------------------------------------------------- #
GRANICA = 200_000


@pytest.mark.parametrize(
    "pomak",
    [pytest.param(-1, id="gv-granica-minus"), pytest.param(0, id="gv-granica")],
)
def test_gzip_pocetna_do_granice_daje_tacne_dokaze(pomak):
    """`perf.html.size` broji raspakovane bajtove, a `perf.compression.missing` vidi gzip."""
    n = GRANICA + pomak
    pocetna = Response(html_od(n), headers={"content-encoding": "gzip"})
    cfg = config(http__max_body_bytes=GRANICA)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, cfg)

    home = snapshot.home
    assert (home.status, home.error_kind, home.html_bytes) == (200, None, n)
    assert home.headers["content-encoding"] == "gzip"
    assert home.title == "Velika"
    rezultati = run_level(1, snapshot)
    assert rezultati["perf.compression.missing"].status == "ok"
    # Prag od 500 kB je iznad granice testa, pa se dokaz proverava na nižem pragu.
    cfg["thresholds"]["perf"]["html_size_kb"] = 100
    ctx = registry.Context(domain=snapshot.domain, industry="ostalo", config=cfg)
    velicina = {r.check_id: r for r in registry.run(1, snapshot, ctx)}["perf.html.size"]
    assert velicina.status == "finding"
    assert velicina.findings[0].evidence["bajtova"] == n


def test_gzip_pocetna_preko_granice_je_greska_sa_razlogom():
    """gv-granica-plus: telo se ne čita dalje, domen je `failed` i razlog kaže zašto."""
    pocetna = Response(html_od(GRANICA + 1), headers={"content-encoding": "gzip"})
    cfg = config(http__max_body_bytes=GRANICA)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, cfg)
        zahtevi = site.paths()

    assert snapshot.entry.status == 200, "server je odgovorio: sajt nije u „Ne rade”"
    assert snapshot.entry.error_kind == PREVELIKO
    assert str(GRANICA) in snapshot.entry.error_detail
    home = snapshot.home
    assert (home.status, home.error_kind, home.html_bytes) == (None, PREVELIKO, 0)
    assert zahtevi.count("/") == 1, "preveliko telo se ne traži ponovo"

    rezultati = run_level(1, snapshot)
    assert rezultati["infra.unreachable"].status == "ok"
    # Bez sadržaja početne nema ni nalaza o njoj, pa ni lažnog „nema naslova”.
    nema_pocetne = {cid for cid, r in rezultati.items() if r.reason and r.reason.code == "requires.home"}
    assert {"perf.html.size", "perf.compression.missing", "seo.title.missing"} <= nema_pocetne
    assert not any(r.status == "finding" for r in rezultati.values())
    report = score.build_report(snapshot, list(rezultati.values()), cfg)
    assert report.status == "failed"
    assert report.reason.code == "entry_error"
    assert reason(report.reason, "sr").startswith(f"{PREVELIKO}: body > {GRANICA} B")


def test_gzip_bomba_kao_pocetna_drzi_memoriju_ispod_granice():
    """64 MiB nula u ~64 kB. httpx bi raspakovao ceo komad od 64 kB odjednom (~64 MiB)."""
    pocetna = Response(bomba(64 * MIB), headers={"content-encoding": "gzip"}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot, vrh = vrh_memorije(lambda: scan(site, config(http__max_body_bytes=MIB)))

    assert snapshot.entry.error_kind == PREVELIKO
    assert vrh < 8 * MIB, f"zauzeto {vrh / MIB:.0f} MiB"


def test_strana_iz_uzorka_preko_granice_ne_prekida_prolaz():
    velika = Response(html_od(GRANICA + 1), headers={"content-encoding": "gzip"})
    with FakeSite(extra={"/usluge": velika}) as site:
        snapshot = scan(site, config(http__max_body_bytes=GRANICA))

    po_adresi = {p.url.removeprefix(site.base_url): p for p in snapshot.pages}
    assert (po_adresi["/usluge"].status, po_adresi["/usluge"].error_kind) == (None, PREVELIKO)
    assert po_adresi["/o-nama"].status == 200
    assert snapshot.home.status == 200


def test_greska_sa_5xx_i_prevelikim_telom_se_ne_ponavlja():
    bomba_500 = Response(bomba(4 * MIB), status=500, headers={"content-encoding": "gzip"}, encoded=True)
    with FakeSite(extra={"/": bomba_500}) as site:
        snapshot = scan(site, config(http__max_body_bytes=MIB))
        zahtevi = site.paths()

    assert (snapshot.entry.status, snapshot.entry.error_kind) == (500, PREVELIKO)
    assert zahtevi.count("/") == 1


def test_sirovi_bajtovi_imaju_istu_granicu():
    """Tok praznih deflate blokova se raspakuje u 13 B; bez granice na sirove bajtove bi tekao
    dok server hoće."""
    pocetna = Response(prazni_blokovi(30_000), headers={"content-encoding": "gzip"}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, config(http__max_body_bytes=100_000))

    assert snapshot.entry.error_kind == PREVELIKO


@pytest.mark.parametrize(
    "pomak, greska",
    [
        pytest.param(-1, None, id="gv-granica-minus"),
        pytest.param(0, None, id="gv-granica"),
        pytest.param(1, PREVELIKO, id="gv-granica-plus"),
    ],
)
def test_granica_bez_kodiranja(pomak, greska):
    pocetna = Response(html_od(GRANICA + pomak))
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, config(http__max_body_bytes=GRANICA))

    assert snapshot.entry.error_kind == greska


# --------------------------------------------------------------------------- #
# Preusmerenja: httpx čita telo svakog koraka bez granice, pa se prate ručno
# --------------------------------------------------------------------------- #
def test_bomba_u_telu_preusmerenja_ne_zauzima_memoriju():
    skok = Response(
        bomba(64 * MIB), status=301, headers={"location": "/dalje", "content-encoding": "gzip"}, encoded=True
    )
    dalje = Response(html("Dalje"))
    with FakeSite(extra={"/": skok, "/dalje": dalje}) as site:
        snapshot, vrh = vrh_memorije(lambda: scan(site, config(http__max_body_bytes=MIB)))

    assert snapshot.home.title == "Dalje"
    assert snapshot.entry.redirect_chain == [f"{site.base_url}/", f"{site.base_url}/dalje"]
    assert snapshot.home.redirect_hops == 1
    assert vrh < 8 * MIB, f"zauzeto {vrh / MIB:.0f} MiB"


def test_petlja_preusmerenja_staje():
    petlja = Response(b"", status=302, headers={"location": "/"})
    with FakeSite(extra={"/": petlja}) as site:
        snapshot = scan(site, config())
        zahtevi = site.paths()

    assert snapshot.entry.error_kind == "too_many_redirects"
    assert zahtevi.count("/") == 21, "početni korak i 20 preusmerenja, kao `max_redirects` u httpx-u"


# --------------------------------------------------------------------------- #
# Kodiranja: isto kao httpx, ali sa granicom
# --------------------------------------------------------------------------- #
def _deflate(telo: bytes, wbits: int) -> bytes:
    packer = zlib.compressobj(9, zlib.DEFLATED, wbits)
    return packer.compress(telo) + packer.flush()


@pytest.mark.parametrize(
    "wbits",
    [pytest.param(zlib.MAX_WBITS, id="ke-zlib-omot"), pytest.param(-zlib.MAX_WBITS, id="ke-goli-deflate")],
)
def test_deflate_sa_omotom_i_bez_njega(wbits):
    """deflate je po RFC-u zlib omot, a stari IIS šalje goli deflate; httpx prihvata oba."""
    telo = html("Deflate")
    pocetna = Response(_deflate(telo, wbits), headers={"content-encoding": "deflate"}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, config())

    assert snapshot.home.title == "Deflate"
    assert snapshot.home.html_bytes == len(telo)


@pytest.mark.parametrize("kodiranje", ["gzip", "deflate"])
def test_pokvareno_kodiranje_je_greska_veze_kao_u_httpx(kodiranje):
    pokvareno = b"\x1f\x8b\x08\x00" + b"\xff" * 64
    pocetna = Response(pokvareno, headers={"content-encoding": kodiranje}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, config())

    assert snapshot.entry.error_kind == "connection"
    assert snapshot.entry.error_detail.startswith("DecodingError")


def test_nepoznato_kodiranje_stize_kako_je_poslato():
    """br bez brotli paketa: httpx ga ne raspakuje, a ni ovde se ne raspakuje."""
    sirovo = b"\x8b\x02\x80nije html\x03"
    pocetna = Response(sirovo, headers={"content-encoding": "br"}, encoded=True)
    with FakeSite(extra={"/": pocetna}) as site:
        snapshot = scan(site, config())

    assert snapshot.home.html_bytes == len(sirovo)
    assert snapshot.home.headers["content-encoding"] == "br"


def test_trazi_se_samo_kodiranje_koje_se_raspakuje_sa_granicom():
    async def zaglavlje():
        async with Fetcher(config()) as fetcher:
            return fetcher._pick_client(verify=True).headers["accept-encoding"]

    assert asyncio.run(zaglavlje()) == "gzip, deflate"
