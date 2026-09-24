import pytest

from skener.config import ConfigError, _validate, get, load_config, multiplier, user_agent


def test_ucitava_podrazumevanu_konfiguraciju():
    cfg = load_config()
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_korisnicka_konfiguracija_se_spaja_a_ne_zamenjuje(tmp_path):
    override = tmp_path / "moj.toml"
    override.write_text("[thresholds.i18n]\nmin_text_length = 100\n", encoding="utf-8")
    cfg = load_config(override)
    assert get(cfg, "thresholds.i18n.min_text_length") == 100
    # ostali pragovi iz iste sekcije prezivljavaju spajanje
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_mnozioci_i_fallback_na_ostalo():
    cfg = load_config()
    assert multiplier(cfg, "hotel", "social") == 1.5
    assert multiplier(cfg, "restoran", "perf") == 1.5
    assert multiplier(cfg, "zdravstvo", "a11y") == 1.5
    assert multiplier(cfg, "nepostojeca-delatnost", "seo") == 1.0


def test_nepostojeci_kljuc_puca_i_imenuje_se():
    cfg = load_config()
    with pytest.raises(ConfigError, match="thresholds.perf.nema_me"):
        get(cfg, "thresholds.perf.nema_me")


def test_parcijalni_mnozilac_ne_razbija_tabelu(tmp_path):
    """Spajanje je ono što čuva ostale kategorije kad korisnik prepiše jednu."""
    override = tmp_path / "moj.toml"
    override.write_text("[industry_multipliers.hotel]\nseo = 9.9\n", encoding="utf-8")
    cfg = load_config(override)
    assert multiplier(cfg, "hotel", "seo") == 9.9
    assert multiplier(cfg, "hotel", "social") == 1.5


def test_nepotpuna_tabela_mnozilaca_puca():
    """Prava granica: neko obriše red u samom skener.toml tokom kalibracije."""
    broken = {
        "severity_points": {"critical": 40, "high": 20, "medium": 8, "low": 3},
        "industry_multipliers": {"hotel": {"seo": 1.2}},
    }
    with pytest.raises(ConfigError, match="industry_multipliers.hotel.social"):
        _validate(broken)


# --------------------------------------------------------------------------- #
# Identitet operatera: User-Agent predstavlja onog ko skenira, ne autora alata.
# Alat se prodaje, pa bi inače svaki kupac skenirao sa autorovim mejlom.
# --------------------------------------------------------------------------- #
@pytest.fixture
def bez_okruzenja(monkeypatch):
    monkeypatch.delenv("SKENER_NAZIV", raising=False)
    monkeypatch.delenv("SKENER_KONTAKT", raising=False)


def test_podrazumevana_konfiguracija_nema_identitet(bez_okruzenja):
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(load_config())


@pytest.mark.parametrize(
    "naziv, kontakt",
    [
        pytest.param("", "kontakt@primer.rs", id="nv-bez-naziva"),
        pytest.param("Web studio Primer", "", id="nv-bez-kontakta"),
        pytest.param("   ", "kontakt@primer.rs", id="nv-samo-razmaci"),
    ],
)
def test_nepotpun_identitet_puca(bez_okruzenja, naziv, kontakt):
    cfg = load_config()
    cfg["identitet"] = {"naziv": naziv, "kontakt": kontakt}
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(cfg)


def test_user_agent_nosi_operatera_a_ne_autora(bez_okruzenja):
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Web studio Primer", "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert "Web studio Primer" in ua and "kontakt@primer.rs" in ua
    assert "miloslazic458" not in ua


def test_identitet_iz_okruzenja_ima_prednost(monkeypatch):
    """Za Docker: `SKENER_NAZIV` i `SKENER_KONTAKT` se prosleđuju iz compose.yaml."""
    monkeypatch.setenv("SKENER_NAZIV", "Iz okruženja")
    monkeypatch.setenv("SKENER_KONTAKT", "env@primer.rs")
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Iz fajla", "kontakt": "fajl@primer.rs"}
    ua = user_agent(cfg)
    assert "Iz okruzenja" in ua and "env@primer.rs" in ua  # ASCII: ž → z


# Pogađanje grešaka: kupac upisuje ime kako mu je prirodno, a HTTP zaglavlje sme da
# nosi samo ASCII. Ime sa „Š" ili ćirilicom inače obori svaki zahtev.
@pytest.mark.parametrize(
    "naziv, ocekivano",
    [
        pytest.param("Web studio Šumadija", "Web studio Sumadija", id="pg-latinica-dijakritici"),
        pytest.param("Đorđe Čačić", "Djordje Cacic", id="pg-dj-i-c"),
        pytest.param("Ђорђе Јовановић", "Djordje Jovanovic", id="pg-cirilica"),
        pytest.param("Студио Љубљана", "Studio Ljubljana", id="pg-cirilica-lj"),
        pytest.param("Studio — Primer", "Studio Primer", id="pg-crta-otpada"),
        pytest.param("Studio 😀 Primer", "Studio Primer", id="pg-emodzi-otpada"),
    ],
)
def test_identitet_se_presipa_u_ascii(bez_okruzenja, naziv, ocekivano):
    cfg = load_config()
    cfg["identitet"] = {"naziv": naziv, "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert ua.isascii(), ua
    assert ocekivano in ua


def test_identitet_ne_moze_da_ubaci_novo_zaglavlje(bez_okruzenja):
    """Novi red u imenu bi u HTTP zahtevu započeo novo zaglavlje."""
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Studio\r\nX-Napad: 1", "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert "\r" not in ua and "\n" not in ua


def test_identitet_od_samih_ne_ascii_znakova_puca(bez_okruzenja):
    cfg = load_config()
    cfg["identitet"] = {"naziv": "😀😀", "kontakt": "kontakt@primer.rs"}
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(cfg)
