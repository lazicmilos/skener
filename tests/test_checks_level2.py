"""Provere nivoa 2 (§7.3). Isti troje: pozitivan, negativan, `unknown` (§12.3)."""

from __future__ import annotations

import pytest

from factories import clean_browser, findings, run_level, statuses
from skener.checks import registry
from skener.models import DomStats, NetworkStats, OversizedImage, TimingStats

LEVEL2_IDS = sorted(s.check_id for s in registry.REGISTRY.values() if s.level == 2)


def test_cista_stranica_nema_nijedan_nalaz():
    results = run_level(2, clean_browser())
    assert findings(results) == set()
    assert set(statuses(results).values()) == {"ok"}


def test_pokrivene_su_sve_registrovane_provere():
    assert sorted(run_level(2, clean_browser())) == LEVEL2_IDS


POZITIVNI = {
    "perf.page.weight": lambda b: setattr(b.network, "total_bytes", 9_000_000),
    "perf.request.count": lambda b: setattr(b.network, "request_count", 175),
    "perf.load.time": lambda b: setattr(b.timing, "load_ms", 9_000),
    "seo.h1.missing": lambda b: setattr(b.dom, "h1_count", 0),
    "seo.h1.multiple": lambda b: setattr(b.dom, "h1_count", 5),
    "a11y.img.alt.missing": lambda b: setattr(
        b, "dom", DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=0)
    ),
    "perf.img.oversized": lambda b: setattr(
        b.dom,
        "oversized_images",
        [
            OversizedImage(src=f"https://cist.rs/s{i}.jpg", natural=[4000, 2667], client=[760, 507], ratio=5.26, est_waste_kb=600)
            for i in range(3)
        ],
    ),
    "qa.console.errors": lambda b: setattr(b.console, "errors", 5),
}


@pytest.mark.parametrize("check_id", LEVEL2_IDS)
def test_pozitivan_nalaz(check_id):
    browser = clean_browser()
    POZITIVNI[check_id](browser)
    result = run_level(2, browser)[check_id]
    assert result.status == "finding", f"{check_id}: očekivan nalaz, dobijeno {result.status}"
    found = result.findings[0]
    assert any(isinstance(v, (int, float)) for v in found.evidence.values())
    assert "{" not in found.message_client and "{" not in found.message_tech
    assert found.level == 2


# --------------------------------------------------------------------------- #
# Stepenasti pragovi: jedan nalaz po proveri, najviša ozbiljnost koja važi (§7.3)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "total_bytes, expected",
    [(1_000_000, None), (2_000_000, "medium"), (4_000_000, "high"), (9_000_000, "critical")],
)
def test_tezina_stranice_stepenasto(total_bytes, expected):
    browser = clean_browser()
    browser.network.total_bytes = total_bytes
    result = run_level(2, browser)["perf.page.weight"]
    if expected is None:
        assert result.status == "ok"
    else:
        assert len(result.findings) == 1, "ne tri nalaza za istu stranicu (§7.3)"
        assert result.findings[0].severity == expected


@pytest.mark.parametrize("count, expected", [(50, None), (120, "medium"), (175, "high")])
def test_broj_zahteva_stepenasto(count, expected):
    browser = clean_browser()
    browser.network.request_count = count
    result = run_level(2, browser)["perf.request.count"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


@pytest.mark.parametrize("load_ms, expected", [(2_000, None), (5_000, "medium"), (9_000, "high")])
def test_vreme_ucitavanja_stepenasto(load_ms, expected):
    browser = clean_browser()
    browser.timing.load_ms = load_ms
    result = run_level(2, browser)["perf.load.time"]
    assert (result.findings[0].severity if expected else result.status) == (expected or "ok")


# --------------------------------------------------------------------------- #
# §7.4 — tri stanja alt atributa, ne dva
# --------------------------------------------------------------------------- #
def test_prazan_alt_nije_greska():
    """`alt=""` je ispravan način da se označi dekorativna slika (§15, zamka 1).

    Alat koji ga prijavljuje kaže klijentu da je pokvareno ono što je urađeno
    kako treba — i ti to pošalješ u mejlu.
    """
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_without_alt_attr=0, images_empty_alt=20)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


def test_evidence_razlikuje_nema_atributa_od_praznog():
    """§12.4, ordinacijadenta.rs: dokaz mora da kaže 28/30 i da razlikuje stanja."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28, images_empty_alt=2)
    evidence = run_level(2, browser)["a11y.img.alt.missing"].findings[0].evidence
    assert evidence["bez_alta"] == 28
    assert evidence["ukupno"] == 30
    assert evidence["prazan_alt"] == 2


def test_malo_slika_ne_pravi_nalaz():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=4, images_without_alt_attr=4)
    assert run_level(2, browser)["a11y.img.alt.missing"].status == "ok"


@pytest.mark.parametrize(
    "industry, expected",
    [("ostalo", "low"), ("hotel", "low"), ("zdravstvo", "medium"), ("institucija", "medium")],
)
def test_ozbiljnost_alta_zavisi_od_delatnosti(industry, expected):
    """Zdravstvo i institucije imaju zakonsku izloženost po pristupačnosti (§7.4)."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=10, images_without_alt_attr=6)
    result = run_level(2, browser, industry=industry)["a11y.img.alt.missing"]
    assert result.findings[0].severity == expected


def test_visok_udeo_prelazi_u_high_bez_obzira_na_delatnost():
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=30, images_without_alt_attr=28)
    result = run_level(2, browser, industry="ostalo")["a11y.img.alt.missing"]
    assert result.findings[0].severity == "high"


# --------------------------------------------------------------------------- #
# `unknown` — merenje u koje nemaš poverenja gore je od merenja kojeg nema (§7.2)
# --------------------------------------------------------------------------- #
def test_previse_neizmerenih_odgovora_je_unknown():
    browser = clean_browser()
    browser.network = NetworkStats(request_count=40, total_bytes=500_000, unmeasured_responses=9)
    result = run_level(2, browser)["perf.page.weight"]
    assert result.status == "unknown"
    assert "nije izmereno" in result.reason


def test_neuspeo_browser_daje_unknown_svuda():
    browser = clean_browser(status="failed")
    results = run_level(2, browser)
    assert sorted(results) == LEVEL2_IDS
    assert set(statuses(results).values()) == {"unknown"}
    assert all(r.reason for r in results.values())


def test_timeout_bez_prekoracenja_praga_je_unknown_a_ne_ok():
    """Merenja posle timeouta su nepotpuna i provere to moraju da znaju (§7.1)."""
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    results = run_level(2, browser)
    assert results["perf.page.weight"].status == "unknown"
    assert results["perf.request.count"].status == "unknown"


def test_timeout_je_sam_po_sebi_nalaz_za_vreme_ucitavanja():
    browser = clean_browser()
    browser.timing = TimingStats(dom_content_loaded_ms=3000, load_ms=None, reached="timeout")
    result = run_level(2, browser)["perf.load.time"]
    assert result.status == "finding"
    assert result.findings[0].severity == "high"


def test_h1_je_unknown_kad_stranica_nije_dovrsila_ucitavanje():
    """Prazan h1 posle timeouta nije nalaz — h1 može da stigne kasnije (§6)."""
    browser = clean_browser()
    browser.dom.h1_count = 0
    browser.timing = TimingStats(load_ms=None, reached="timeout")
    assert run_level(2, browser)["seo.h1.missing"].status == "unknown"


def test_nula_predimenzioniranih_uz_nemerene_slike_je_unknown():
    """Bez ovoga ne znaš da li je „0 predimenzioniranih" nalaz ili neuspelo merenje (§3.3)."""
    browser = clean_browser()
    browser.dom = DomStats(h1_count=1, images_total=20, images_unmeasured=15)
    result = run_level(2, browser)["perf.img.oversized"]
    assert result.status == "unknown"
    assert "nije izmereno" in result.reason


def test_veliki_visak_bajtova_pali_nalaz_i_ispod_tri_slike():
    """Prag je ≥ 3 slike **ili** višak > 700 kB (§7.3)."""
    browser = clean_browser()
    browser.dom.oversized_images = [
        OversizedImage(src="https://cist.rs/hero.jpg", natural=[4000, 2667], client=[760, 507], ratio=5.26, est_waste_kb=1840)
    ]
    assert run_level(2, browser)["perf.img.oversized"].status == "finding"
