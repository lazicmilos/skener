"""JSON izveštaj: ugovor sa verzijom šeme, koji se ne menja tiho."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
from factories import clean_browser

from skener import pipeline, store
from skener.checks import registry
from skener.config import load_config
from skener.messages import reason
from skener.models import CheckResult, to_jsonable
from skener.report import json_out

FIXTURES = Path(__file__).parent / "fixtures"
SEMA = json.loads(files("skener").joinpath("schema/report-2.json").read_text(encoding="utf-8"))


def test_json_izvestaj_prolazi_semu(tmp_path):
    rezultat = pipeline.recheck(FIXTURES, load_config())
    path = json_out.write(tmp_path / "report.json", rezultat)
    dokument = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(dokument, SEMA)
    assert list(dokument)[:2] == ["schema_version", "scanner_version"], "verzija je na vrhu dokumenta"


def test_json_nema_recenica():
    """Rečenica se pravi iz dokaza na jeziku čitaoca; u ugovoru bi bila na jednom jeziku zauvek."""
    dokument = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    nalazi = [f for r in dokument["ranked"] for f in r["findings"]]
    assert nalazi and not [f for f in nalazi if {"message_client", "message_tech"} & set(f)]


def test_sema_odbija_nepoznato_polje():
    """`additionalProperties: false`: novo polje mora prvo u šemu, pa tek onda u izlaz."""
    dokument = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    dokument["ranked"][0]["novo_polje"] = 1
    with pytest.raises(jsonschema.ValidationError, match="novo_polje"):
        jsonschema.validate(dokument, SEMA)


# --------------------------------------------------------------------------- #
# Snapshoti iz 1.x ostaju čitljivi: na njima je kalibrisana lista A
# --------------------------------------------------------------------------- #
@pytest.fixture
def provera_novog_polja(monkeypatch):
    """Provera nivoa 2 koja čita polje uvedeno u v2, kakvih će biti u F2."""
    pozvana = []

    def fn(snapshot, ctx):
        pozvana.append(snapshot.domain)
        return CheckResult(check_id="test.novo.polje", status="ok")

    spec = registry.CheckSpec(
        check_id="test.novo.polje",
        level=2,
        category="perf",
        base_severity="low",
        requires=("browser", "v2:network.bytes_at_load"),
        description="proba",
        threshold="proba",
        fn=fn,
    )
    registry.load_all()
    monkeypatch.setitem(registry.REGISTRY, spec.check_id, spec)
    return pozvana


def test_v1_snapshot_daje_unknown_a_ne_pad(provera_novog_polja):
    (_site, browser), *_ = [(s, b) for s, b in store.read_all(FIXTURES) if b is not None]
    assert browser.scanner_version.startswith("1.")
    ctx = registry.Context(domain=browser.domain, industry="ostalo", config=load_config())
    rezultat = {r.check_id: r for r in registry.run(2, browser, ctx)}["test.novo.polje"]
    assert rezultat.status == "unknown"
    ocekivano = f"snapshot iz verzije {browser.scanner_version} nema network.bytes_at_load"
    assert reason(rezultat.reason) == ocekivano
    assert provera_novog_polja == [], "provera se ne izvršava nad snapshotom koji nema polje"


def test_v2_snapshot_izvrsava_proveru(provera_novog_polja):
    browser = clean_browser()
    ctx = registry.Context(domain=browser.domain, industry="ostalo", config=load_config())
    rezultat = {r.check_id: r for r in registry.run(2, browser, ctx)}["test.novo.polje"]
    assert rezultat.status == "ok" and provera_novog_polja == [browser.domain]
