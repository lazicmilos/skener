"""Broj i imenica u srpskom (§3.5): rečenica ide pravo u mejl, pa mora biti pravilna."""

from __future__ import annotations


def decimalni(broj: float) -> str:
    """„14,9", „22", „0,1" — decimalni zarez i bez „,0", kako se piše u mejlu (BUG-015)."""
    return f"{broj:.1f}".removesuffix(".0").replace(".", ",")


def sa_brojem(broj: int, jednina: str, paukal: str, mnozina: str) -> str:
    """„1 stranica", „3 stranice", „5 stranica", „21 stranica", „12 stranica".

    Srpski bira oblik po poslednjoj cifri, osim za 11–14: jednina posle 1 (ali ne
    11), paukal posle 2–4 (ali ne 12–14), množina za sve ostalo. Oblike daje
    pozivalac, jer zavise i od padeža: „ima 21 grešku", ali „od 21 slike".
    """
    if broj % 10 == 1 and broj % 100 != 11:
        oblik = jednina
    elif 2 <= broj % 10 <= 4 and not 12 <= broj % 100 <= 14:
        oblik = paukal
    else:
        oblik = mnozina
    return f"{broj} {oblik}"
