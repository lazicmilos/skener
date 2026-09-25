"""Ulaz koji daje korisnik: lista domena i drugi CSV-ovi iz Excel-a.

Greška u ulazu je `InputError`, a ne `SystemExit`. Isti ulaz čitaju CLI i web worker,
pa odluku o tome šta se radi sa greškom donosi pozivalac: CLI je ispisuje i izlazi, a
worker je vraća korisniku. Upozorenja se vraćaju, a ne loguju, iz istog razloga.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from skener.models import INDUSTRIES, DomainInput


class InputError(ValueError):
    """Ulaz koji ne može da se obradi. Poruka navodi izvor i, kad postoji, broj reda."""


@dataclass
class InputWarning:
    """Ulaz je obrađen, ali uz izmenu koju korisnik treba da vidi."""

    message: str
    row: int | None = None
    domain: str | None = None


@dataclass
class CsvTable:
    fieldnames: list[str]
    # (broj reda kako ga prikazuje Excel, vrednosti): po broju korisnik nađe red
    rows: list[tuple[int, dict[str, str]]]
    header_row: int = 1
    warnings: list[InputWarning] = field(default_factory=list)


def read_excel_csv(data: bytes, source: str) -> CsvTable:
    """CSV kakav pravi Excel na srpskom Windows-u.

    Bez opcije „CSV UTF-8" Excel čuva u windows-1250, a srpska podešavanja Windows-a
    kolone razdvajaju sa `;`, ne sa zarezom. Broj reda je broj zapisa, a ne linije u
    fajlu: ćelija sa prelomom reda je u Excel-u jedan red, a u fajlu dve linije.
    """
    warnings: list[InputWarning] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append(InputWarning(f"{source} nije u UTF-8, čitam ga kao windows-1250"))
        text = data.decode("cp1250", errors="replace")
    header = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=header.count) if any(c in header for c in ",;\t") else ","
    records = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))

    header_at = next((i for i, values in enumerate(records) if values), None)
    if header_at is None:
        return CsvTable([], [], warnings=warnings)
    fieldnames = records[header_at]
    rows = [
        (i + 1, dict(zip(fieldnames, values, strict=False)))
        for i, values in enumerate(records)
        if i > header_at and values
    ]
    return CsvTable(fieldnames, rows, header_at + 1, warnings)


def read_domain_list(data: bytes, source: str) -> tuple[list[DomainInput], list[InputWarning]]:
    """Lista domena (§4.1): CSV sa zaglavljem `domain,industry,note`, ne gola lista.

    Isti domen dva puta znači dva prolaza kroz tuđ sajt, pa važi prvo pojavljivanje.
    """
    table = read_excel_csv(data, source)
    warnings = table.warnings
    if "domain" not in table.fieldnames:
        raise InputError(f"{source}, red {table.header_row}: nedostaje kolona `domain` u zaglavlju (§4.1)")

    domains: list[DomainInput] = []
    seen: set[str] = set()
    for row_no, row in table.rows:
        domain = (row.get("domain") or "").strip()
        if not domain or domain.startswith("#"):
            continue
        if domain.lower() in seen:
            warnings.append(InputWarning("domen se ponavlja u listi, preskačem ga", row_no, domain))
            continue
        seen.add(domain.lower())
        industry = (row.get("industry") or "").strip().lower() or "ostalo"
        if industry not in INDUSTRIES:
            warnings.append(
                InputWarning(f"nepoznata delatnost {industry!r}, koristim `ostalo`", row_no, domain)
            )
            industry = "ostalo"
        domains.append(DomainInput(domain=domain, industry=industry, note=(row.get("note") or "").strip()))
    if not domains:
        raise InputError(f"{source}: nijedan domen nije učitan")
    return domains, warnings
