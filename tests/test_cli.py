"""CLI i izveštaji od kraja do kraja (§10, §11)."""

from __future__ import annotations

import csv
import json

import pytest
from localserver import FakeSite, Response, html

from skener import cli
from skener.config import load_config
from skener.models import DomainReport, Finding
from skener.report import csv_out, html_out
from skener.score import rank


# --------------------------------------------------------------------------- #
# Ulazni CSV (§4.1)
# --------------------------------------------------------------------------- #
def test_cita_csv_sa_zaglavljem(tmp_path):
    path = tmp_path / "domains.csv"
    path.write_text(
        "domain,industry,note\nmensa.rs,institucija,beleska\nangolo.rs,,\n"
        "protetica.com,NEPOSTOJECA,\n\n",
        encoding="utf-8",
    )
    rows = cli.read_domains(path)
    assert [r.domain for r in rows] == ["mensa.rs", "angolo.rs", "protetica.com"]
    assert rows[0].industry == "institucija" and rows[0].note == "beleska"
    assert rows[1].industry == "ostalo", "prazna delatnost pada na `ostalo` (§4.1)"
    assert rows[2].industry == "ostalo", "nepoznata delatnost pada na `ostalo`, ne ruši prolaz"


def test_only_filtrira(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("domain,industry\na.rs,hotel\nb.rs,hotel\n", encoding="utf-8")
    assert [r.domain for r in cli.read_domains(path, ["B.RS"])] == ["b.rs"]


def test_csv_bez_kolone_domain_puca_razumljivo(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("sajt,industry\na.rs,hotel\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="domain"):
        cli.read_domains(path)


# --------------------------------------------------------------------------- #
# scan → recheck (§11.1)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def prolaz(tmp_path_factory):
    """Dva lokalna sajta: jedan uredan, jedan sa lažnim 404 i bez OG oznaka.

    Jedan prolaz za ceo modul: podizanje servera i pun scan traju, a svi testovi
    ispod gledaju isti rezultat.
    """
    tmp_path = tmp_path_factory.mktemp("prolaz")
    # `--config` se spaja preko skener.toml; ovde gasimo pauze da testovi ne traju minut.
    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")

    with FakeSite() as cist, FakeSite(soft404=True, extra={"/": Response(html("Bez oznaka"))}) as los:
        domains = tmp_path / "domains.csv"
        domains.write_text(
            f"domain,industry,note\n{cist.base_url},hotel,\n{los.base_url},restoran,\n",
            encoding="utf-8",
        )
        out = tmp_path / "izvestaj"
        code = cli.main(
            ["scan", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )
        yield code, out, cist, los


def test_scan_pravi_sve_izlaze(prolaz):
    code, out, _cist, _los = prolaz
    assert code == 0
    assert (out / "index.html").is_file()
    assert (out / "findings.csv").is_file()
    assert (out / "summary.csv").is_file()
    assert list((out / "snapshots").glob("*/site.json")), "snapshoti se uvek pišu (§2.2)"


def test_summary_ima_red_po_domenu(prolaz):
    _code, out, _cist, _los = prolaz
    rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert set(rows[0]) == set(csv_out.SUMMARY_HEADER)
    assert {r["industry"] for r in rows} == {"hotel", "restoran"}
    assert [int(r["rank"]) for r in rows] == [1, 2]


def test_findings_ima_red_po_nalazu_sa_dokazom(prolaz):
    _code, out, _cist, _los = prolaz
    rows = list(csv.DictReader((out / "findings.csv").open(encoding="utf-8")))
    assert rows, "loš sajt mora da proizvede bar jedan nalaz"
    assert set(rows[0]) == set(csv_out.FINDINGS_HEADER)
    for row in rows:
        assert json.loads(row["evidence_json"]), "svaki nalaz nosi dokaz (§3.5)"
        assert row["message_client"] and "{" not in row["message_client"]


def test_recheck_daje_isti_rezultat_bez_ijednog_zahteva(prolaz, tmp_path):
    """Kalibracija bez ponovnog prolaza je cela poenta podele iz §2.1."""
    _code, out, cist, los = prolaz
    prvi = (out / "summary.csv").read_text(encoding="utf-8")
    pre = len(cist.requests) + len(los.requests)

    ponovo = tmp_path / "ponovo"
    assert cli.main(["recheck", str(out / "snapshots"), "--out", str(ponovo)]) == 0

    assert len(cist.requests) + len(los.requests) == pre, "recheck ne sme da dodirne mrežu"
    assert (ponovo / "summary.csv").read_text(encoding="utf-8") == prvi


def test_html_je_samostalan(prolaz):
    """Bez CDN-a: izveštaj se otvara i bez mreže (§10.2)."""
    _code, out, _cist, _los = prolaz
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<style>" in page and "<script>" in page
    assert "cdn" not in page.lower()
    assert 'src="http' not in page and "@import" not in page
    assert "0,6 MB/s" in page or "MB/s" in page, "pretpostavka za brzinu mora biti u fusnoti (§10.3)"


def test_record_snima_gzipovane_fixture_e(tmp_path):
    """§12.2: bez sirovog HTML-a ostalih strana, inače repo naraste."""
    from skener import store

    config = tmp_path / "brzo.toml"
    config.write_text("[http]\ndelay_ms = [0, 0]\n", encoding="utf-8")
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},hotel\n", encoding="utf-8")
        out = tmp_path / "fixtures"
        code = cli.main(
            ["record", str(domains), "--out", str(out), "--level", "1", "--config", str(config)]
        )

    assert code == 0
    assert list(out.glob("*/site.json.gz")), "fixture-i se pišu gzipovani"
    (snimljen, _browser) = next(iter(store.read_all(out)))
    assert snimljen.home.raw_html, "sirovi HTML početne ostaje (treba za eskalaciju)"
    assert all(p.raw_html is None for p in snimljen.pages[1:])


# --------------------------------------------------------------------------- #
# HTML izveštaj — sadržaj
# --------------------------------------------------------------------------- #
def _izvestaj(**kwargs) -> DomainReport:
    finding = Finding(
        domain="d.rs",
        check_id="seo.canonical.duplicate",
        level=1,
        category="seo",
        severity="critical",
        message_client="Sve stranice prijavljuju istu adresu kao zvaničnu.",
        message_tech="canonical_normalized identičan na 5 stranica",
        evidence={"stranica": 5},
        evidence_urls=["https://d.rs/a"],
        weight=40.0,
    )
    base = {"domain": "d.rs", "industry": "hotel", "findings": [finding], "total_score": 40.0,
            "max_finding_weight": 40.0, "rank": 1}
    return DomainReport(**{**base, **kwargs})


def test_ozbiljnost_ima_oznaku_i_znak_a_ne_samo_boju():
    """Boje moraju biti razlučive i u sivim tonovima i za daltoniste (§10.2)."""
    page = html_out.render([_izvestaj()], load_config())
    assert "KRITIČNO" in page and "▲" in page


def test_nacrt_mejla_ima_tri_recenice():
    report = _izvestaj()
    nacrt = html_out.email_draft(report)
    assert report.domain in nacrt
    assert "1. Sve stranice prijavljuju" in nacrt


def test_nacrt_mejla_za_cist_sajt_ne_izmislja_probleme():
    report = DomainReport(domain="cist.rs", industry="zdravstvo")
    assert "nisam našao" in html_out.email_draft(report)


def test_html_bezi_od_html_a_iz_sadrzaja_sajta():
    """Naslovi i adrese dolaze sa tuđeg sajta — moraju da se eskejpuju."""
    report = _izvestaj()
    report.findings[0].message_client = '<script>alert("xss")</script>'
    page = html_out.render([report], load_config())
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_unknown_razlozi_se_prikazuju():
    from skener.models import Unknown

    report = _izvestaj(unknowns=[Unknown(check_id="perf.page.weight", reason="9 odgovora nemereno")])
    page = html_out.render([report], load_config())
    assert "9 odgovora nemereno" in page
    assert "perf.page.weight" in page


def test_bom_se_pise_samo_kad_se_trazi(tmp_path):
    reports = rank([_izvestaj()])
    sa = csv_out.write_summary(tmp_path / "sa.csv", reports, bom=True)
    bez = csv_out.write_summary(tmp_path / "bez.csv", reports, bom=False)
    assert sa.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not bez.read_bytes().startswith(b"\xef\xbb\xbf")


# --------------------------------------------------------------------------- #
# explain (§11.1)
# --------------------------------------------------------------------------- #
def test_explain_ispisuje_prag_i_recenicu(capsys):
    assert cli.main(["explain", "seo.canonical.duplicate"]) == 0
    ispis = capsys.readouterr().out
    assert "critical" in ispis and "3 stranice" in ispis
    assert "rečenica za klijenta" in ispis


def test_explain_nepoznate_provere_predlaze_slicne():
    with pytest.raises(SystemExit, match="canonical"):
        cli.main(["explain", "canonical"])


def test_explain_all_markdown_pokriva_sve_provere(capsys):
    from skener.checks import registry

    assert cli.main(["explain", "--all", "--markdown"]) == 0
    ispis = capsys.readouterr().out
    registry.load_all()
    for check_id in registry.REGISTRY:
        assert f"`{check_id}`" in ispis, f"{check_id} fali u tabeli za README"


def test_scan_bez_identiteta_odbija_pre_ijednog_zahteva(tmp_path, monkeypatch):
    """Bez imena i kontakta operatera nema skeniranja — ni jednog zahteva."""
    monkeypatch.delenv("SKENER_NAZIV", raising=False)
    monkeypatch.delenv("SKENER_KONTAKT", raising=False)
    with FakeSite() as site:
        domains = tmp_path / "d.csv"
        domains.write_text(f"domain,industry\n{site.base_url},ostalo\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="identitet"):
            cli.main(["scan", str(domains), "--out", str(tmp_path / "izlaz"), "--level", "1"])
        assert site.requests == [], f"zahtevi pre provere identiteta: {site.requests}"
