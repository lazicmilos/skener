import pytest

from skener.config import ConfigError, _validate, get, load_config, multiplier


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
