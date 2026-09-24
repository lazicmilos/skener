"""Statičko testiranje rečenica za klijenta — recenzija pretvorena u testove.

Rečenica ide pravo u mejl, pa mora biti tačna i pravilna. Tri vrste pravila:
svaki broj potiče iz dokaza (BUG-013), ispravljene netačne tvrdnje se ne vraćaju,
a broj i imenica se slažu po pravilima srpskog (BUG-014).
"""

from __future__ import annotations

import re

import pytest
from factories import clean_browser, clean_site, run_level

from skener.checks import registry
from skener.checks.srpski import sa_brojem

registry.load_all()
SPECS = sorted(registry.REGISTRY.values(), key=lambda s: s.check_id)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.check_id)
def test_svaki_broj_u_recenici_potice_iz_dokaza(spec):
    """Broj upisan napamet („sekunda i po") ne sme u rečenicu za klijenta."""
    bez_mesta_za_dokaz = re.sub(r"\{[^}]*\}", "", spec.message_template)
    bez_mesta_za_dokaz = re.sub(r"\bh1\b", "", bez_mesta_za_dokaz)  # ime HTML oznake, ne broj
    assert not re.search(r"\d", bez_mesta_za_dokaz), bez_mesta_za_dokaz


@pytest.mark.parametrize(
    "tvrdnja",
    [
        pytest.param("sekunda i po", id="izmisljen-broj"),
        pytest.param("Sve proverene", id="sve-umesto-tri"),
        pytest.param("nasumičnu", id="google-bira-nasumicno"),
        pytest.param("gola adresa", id="og-title-bez-naslova"),
        pytest.param("prosečnoj mobilnoj", id="spora-veza-kao-prosecna"),
        pytest.param("Pretraživaču nije jasno", id="vise-h1-zbunjuje-google"),
        pytest.param("neograničen broj", id="soft404-neograniceno"),
        pytest.param("najčešće na starijim", id="konzola-stari-telefoni"),
    ],
)
def test_ispravljena_netacna_tvrdnja_se_ne_vraca(tvrdnja):
    assert not [s.check_id for s in SPECS if tvrdnja in s.message_template]


def test_usteda_od_kompresije_se_racuna_iz_velicine():
    """80 kB, na četvrtinu → 60 kB manje; na 0,6 MB/s to je 0,1 s, ne „sekunda i po"."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 80_000
    nalaz = run_level(1, site)["perf.compression.missing"].findings[0]
    assert nalaz.evidence["usteda_s"] == 0.1
    assert "0,1 s" in nalaz.message_client
    assert nalaz.severity == "low"


# --------------------------------------------------------------------------- #
# Srpski broj: granične vrednosti pravila (1 | 2–4 | 5–20 | 11–14 | 21 | 22 | 111…)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "broj, ocekivano",
    [
        pytest.param(1, "1 stranica", id="gv-1"),
        pytest.param(2, "2 stranice", id="gv-2"),
        pytest.param(4, "4 stranice", id="gv-4"),
        pytest.param(5, "5 stranica", id="gv-5"),
        pytest.param(11, "11 stranica", id="gv-11-izuzetak"),
        pytest.param(12, "12 stranica", id="gv-12-izuzetak"),
        pytest.param(14, "14 stranica", id="gv-14-izuzetak"),
        pytest.param(15, "15 stranica", id="gv-15"),
        pytest.param(21, "21 stranica", id="gv-21"),
        pytest.param(22, "22 stranice", id="gv-22"),
        pytest.param(25, "25 stranica", id="ke-25"),
        pytest.param(0, "0 stranica", id="gv-0"),
        pytest.param(101, "101 stranica", id="gv-101"),
        pytest.param(111, "111 stranica", id="gv-111-izuzetak"),
        pytest.param(112, "112 stranica", id="gv-112-izuzetak"),
        pytest.param(122, "122 stranice", id="gv-122"),
    ],
)
def test_srpski_broj(broj, ocekivano):
    assert sa_brojem(broj, "stranica", "stranice", "stranica") == ocekivano


@pytest.mark.parametrize(
    "h1, ocekivano",
    [
        pytest.param(4, "4 glavna naslova", id="paukal"),
        pytest.param(5, "5 glavnih naslova", id="mnozina"),
        pytest.param(21, "21 glavni naslov", id="jednina"),
    ],
)
def test_poruka_o_vise_h1_je_pravilna(h1, ocekivano):
    browser = clean_browser()
    browser.dom.h1_count = h1
    poruka = run_level(2, browser)["seo.h1.multiple"].findings[0].message_client
    assert ocekivano in poruka, poruka


@pytest.mark.parametrize(
    "greske, ocekivano",
    [
        pytest.param(4, "4 JavaScript greške", id="paukal"),
        pytest.param(7, "7 JavaScript grešaka", id="mnozina"),
        pytest.param(21, "21 JavaScript grešku", id="jednina-akuzativ"),
    ],
)
def test_poruka_o_greskama_u_konzoli_je_pravilna(greske, ocekivano):
    browser = clean_browser()
    browser.console.errors = greske
    poruka = run_level(2, browser)["qa.console.errors"].findings[0].message_client
    assert ocekivano in poruka, poruka


@pytest.mark.parametrize(
    "zahteva, ocekivano",
    [
        pytest.param(101, "101 odvojeno preuzimanje", id="jednina"),
        pytest.param(102, "102 odvojena preuzimanja", id="paukal"),
        pytest.param(150, "150 odvojenih preuzimanja", id="mnozina"),
    ],
)
def test_poruka_o_broju_zahteva_je_pravilna(zahteva, ocekivano):
    browser = clean_browser()
    browser.network.request_count = zahteva
    poruka = run_level(2, browser)["perf.request.count"].findings[0].message_client
    assert ocekivano in poruka, poruka


def _isti(site, polje: str, broj: int) -> None:
    """`broj` stranica sa istom vrednošću, svaka u svojoj grupi putanja."""
    for i, page in enumerate(site.pages[:broj]):
        setattr(page, polje, "Ista vrednost na više stranica")
        page.final_url = "https://cist.rs/" if i == 0 else f"https://cist.rs/g{i}/strana"


@pytest.mark.parametrize(
    "broj, ocekivano",
    [pytest.param(3, "3 kopije", id="paukal"), pytest.param(5, "5 kopija", id="mnozina")],
)
def test_poruka_o_istom_naslovu_je_pravilna(broj, ocekivano):
    site = clean_site()
    _isti(site, "title", broj)
    poruka = run_level(1, site)["seo.title.duplicate"].findings[0].message_client
    assert f"kao {ocekivano} iste stranice" in poruka, poruka


@pytest.mark.parametrize(
    "broj, ocekivano",
    [pytest.param(3, "3 stranice", id="paukal"), pytest.param(5, "5 stranica", id="mnozina")],
)
def test_poruka_o_istom_opisu_je_pravilna(broj, ocekivano):
    site = clean_site()
    _isti(site, "meta_description", broj)
    poruka = run_level(1, site)["seo.description.duplicate"].findings[0].message_client
    assert f"između {ocekivano}." in poruka, poruka


# --------------------------------------------------------------------------- #
# BUG-015: decimalni zarez, kako se piše u mejlu („14,9 MB", ne „14.9 MB")
# --------------------------------------------------------------------------- #
def test_brojevi_u_recenici_imaju_decimalni_zarez():
    browser = clean_browser()
    browser.network.total_bytes = 14_900_000
    browser.network.bytes_by_type = {"image": 14_900_000}
    nalaz = run_level(2, browser)["perf.page.weight"].findings[0]
    assert "14,9 MB" in nalaz.message_client and "4,8 Mb/s" in nalaz.message_client
    assert nalaz.evidence["mb"] == 14.9, "dokaz ostaje broj; menja se samo zapis u rečenici"
    assert "14.9" in nalaz.message_tech, "tehnički opis ostaje sa tačkom"


def test_ceo_broj_nema_nulu_iza_zareza():
    browser = clean_browser()
    browser.network.total_bytes = 30_000_000
    browser.network.bytes_by_type = {"media": 8_000_000, "image": 22_000_000}
    poruka = run_level(2, browser)["perf.page.weight"].findings[0].message_client
    assert "prenosi 22 MB (video dodatno 8 MB)" in poruka, poruka


# --------------------------------------------------------------------------- #
# Tačne vrednosti brojeva u rečenici — mutaciono testiranje je pokazalo da nijedan
# test ne proverava formulu, pa bi `/ 8` → `/ 9` prošlo neprimećeno.
# --------------------------------------------------------------------------- #
def test_sekunde_na_mobilnoj_vezi_se_racunaju_tacno():
    """14,9 MB na 0,6 MB/s = 24,83 s, plus 1 s režije = 25,8 s."""
    browser = clean_browser()
    browser.network.total_bytes = 14_900_000
    browser.network.bytes_by_type = {"image": 14_900_000}
    nalaz = run_level(2, browser)["perf.page.weight"].findings[0]
    assert nalaz.evidence["sekundi"] == 25.8
    assert nalaz.evidence["brzina"] == 4.8


def test_usteda_od_kompresije_tacna_vrednost():
    """1,2 MB HTML-a, četvrtina ostaje: 0,9 MB manje na 0,6 MB/s = 1,5 s."""
    site = clean_site()
    site.home.headers = {}
    site.home.html_bytes = 1_200_000
    assert run_level(1, site)["perf.compression.missing"].findings[0].evidence["usteda_s"] == 1.5


@pytest.mark.parametrize(
    "izvor, ocekivano",
    [
        pytest.param("sitemap", "sitemap", id="ke-sitemap"),
        pytest.param("links", "interni linkovi", id="ke-linkovi"),
    ],
)
def test_dokaz_kaze_odakle_je_uzorak(izvor, ocekivano):
    """Uzorak iz linkova je manje pouzdan od uzorka iz mape sajta (§4.4), pa to piše u dokazu."""
    site = clean_site(sample_source=izvor)
    _isti(site, "title", 3)
    assert run_level(1, site)["seo.title.duplicate"].findings[0].evidence["uzorak"].startswith(ocekivano)
