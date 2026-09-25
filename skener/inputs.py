"""Ulaz koji daje korisnik. Greška u njemu je `InputError`, a ne `SystemExit`.

Isti ulaz čitaju CLI i web worker, pa odluku o tome šta se radi sa greškom donosi
pozivalac: CLI je ispisuje i izlazi, a worker je vraća korisniku.
"""

from __future__ import annotations


class InputError(ValueError):
    """Ulaz koji ne može da se obradi: prazna lista, folder bez snapshota."""
