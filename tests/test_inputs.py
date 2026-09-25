"""Lista domena i CSV iz Excel-a (§4.1). Lista najčešće stiže iz Excel-a, a kupac nije programer."""

from __future__ import annotations

import pytest

from skener.inputs import InputError, read_domain_list, read_excel_csv


def procitaj(sadrzaj: str | bytes):
    data = sadrzaj.encode("utf-8") if isinstance(sadrzaj, str) else sadrzaj
    return read_domain_list(data, "d.csv")


def test_cita_csv_sa_zaglavljem():
    rows, _ = procitaj(
        "domain,industry,note\nmensa.rs,institucija,beleska\nangolo.rs,,\nprotetica.com,NEPOSTOJECA,\n\n"
    )
    assert [r.domain for r in rows] == ["mensa.rs", "angolo.rs", "protetica.com"]
    assert rows[0].industry == "institucija" and rows[0].note == "beleska"
    assert rows[1].industry == "ostalo", "prazna delatnost pada na `ostalo` (§4.1)"
    assert rows[2].industry == "ostalo", "nepoznata delatnost pada na `ostalo`, ne ruši prolaz"


def test_csv_bez_kolone_domain_puca_razumljivo():
    with pytest.raises(InputError, match="red 1: nedostaje kolona `domain`"):
        procitaj("sajt,industry\na.rs,hotel\n")


@pytest.mark.parametrize(
    "sadrzaj",
    [
        pytest.param(b"", id="nv-prazan-fajl"),
        pytest.param(b"domain,industry\n", id="nv-samo-zaglavlje"),
        pytest.param(b"domain,industry\n\n  \n", id="nv-prazni-redovi"),
    ],
)
def test_csv_bez_domena_puca_razumljivo(sadrzaj):
    with pytest.raises(InputError):
        procitaj(sadrzaj)


# --------------------------------------------------------------------------- #
# Pogađanje grešaka: lista iz Excel-a na srpskom Windows-u
# --------------------------------------------------------------------------- #
def test_csv_iz_excela_sa_tackom_zarezom():
    """Srpska podešavanja Windows-a: Excel „CSV" razdvaja kolone sa `;`."""
    rows, _ = procitaj("domain;industry;note\nmensa.rs;institucija;beleška\n")
    assert [(r.domain, r.industry, r.note) for r in rows] == [("mensa.rs", "institucija", "beleška")]


def test_csv_u_windows_1250():
    """Excel bez „UTF-8" opcije čuva u windows-1250; ranije je ovo bio traceback."""
    rows, upozorenja = procitaj("domain,industry,note\nmensa.rs,institucija,čćžšđ\n".encode("cp1250"))
    assert rows[0].note == "čćžšđ"
    assert "windows-1250" in upozorenja[0].message


def test_csv_duplikati_se_skeniraju_jednom():
    """Isti domen dva puta = dva puta tuđ sajt i dva reda u izveštaju sa istim snapshotom."""
    rows, _ = procitaj("domain,industry\nmensa.rs,institucija\nMENSA.RS,hotel\nangolo.rs,restoran\n")
    assert [r.domain for r in rows] == ["mensa.rs", "angolo.rs"]
    assert rows[0].industry == "institucija", "važi prvo pojavljivanje"


def test_csv_sa_bom_oznakom():
    rows, _ = procitaj("domain,industry\nmensa.rs,institucija\n".encode("utf-8-sig"))
    assert [r.domain for r in rows] == ["mensa.rs"]


# --------------------------------------------------------------------------- #
# Broj reda: po njemu korisnik nađe red u Excel-u
# --------------------------------------------------------------------------- #
def test_upozorenje_nosi_broj_reda_i_domen():
    _, upozorenja = procitaj("domain,industry\nmensa.rs,institucija\nangolo.rs,picerija\nMENSA.RS,hotel\n")
    assert [(u.row, u.domain) for u in upozorenja] == [(3, "angolo.rs"), (4, "MENSA.RS")]


@pytest.mark.parametrize(
    ("sadrzaj", "redovi"),
    [
        pytest.param(b"domain\na.rs\nb.rs\n", [2, 3], id="ke-obican"),
        pytest.param(b"domain\na.rs\n\nb.rs\n", [2, 4], id="pg-prazan-red-se-broji"),
        pytest.param(b'domain,note\na.rs,"prvi\ndrugi"\nb.rs,x\n', [2, 3], id="pg-prelom-u-celiji"),
    ],
)
def test_broj_reda_je_red_u_excelu(sadrzaj, redovi):
    """Prazan red Excel prikazuje; ćelija sa prelomom je u fajlu dve linije, a u Excel-u jedan red."""
    assert [broj for broj, _ in read_excel_csv(sadrzaj, "d.csv").rows] == redovi


def test_zaglavlje_posle_praznog_reda():
    tabela = read_excel_csv(b"\ndomain;industry\na.rs;hotel\n", "d.csv")
    assert tabela.header_row == 2 and tabela.rows == [(3, {"domain": "a.rs", "industry": "hotel"})]
