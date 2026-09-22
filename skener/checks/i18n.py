"""Jezičke provere (§5, §5.1)."""

from __future__ import annotations

import re

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
NEODREDJEN_KOD = {"zxx", "und", "xx"}
DIJAKRITICI = frozenset("čćšžđČĆŠŽĐ")


def _is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def detect_language(text: str, cyr_ratio: float, dia_ratio: float) -> str:
    """Vraća `sr` ili `neodređeno` — nikad `en` (§5.1, tačka 3).

    Engleski od srpskog pisanog bez dijakritika ne možeš da razlikuješ, a takvih
    sajtova ima. Kad ne znaš, provera je `ok`, ne nalaz.
    """
    cyr = lat = dia = 0
    for ch in text:
        if _is_cyrillic(ch):
            cyr += 1
        elif ch.isalpha():
            lat += 1
            if ch in DIJAKRITICI:
                dia += 1
    if cyr + lat == 0:
        return "neodređeno"
    if cyr / (cyr + lat) > cyr_ratio:
        return "sr"
    if lat and dia / lat > dia_ratio:
        return "sr"
    return "neodređeno"


def _lang_usable(lang: str | None) -> bool:
    """Ima li smisla porediti ovaj `lang` sa sadržajem."""
    if not lang:
        return False
    value = lang.strip()
    return bool(value) and value.lower() not in NEODREDJEN_KOD and bool(BCP47.match(value))


@check(
    "i18n.lang.missing",
    level=1,
    category="i18n",
    base_severity="medium",
    requires=["home"],
    description="<html> nema atribut lang.",
    threshold="atribut lang ne postoji",
    message=(
        "U kodu sajta nigde ne piše na kom je jeziku. Pretraživači zato nagađaju kom tržištu "
        "da ga nude, a čitači ekrana ga izgovaraju pogrešnim izgovorom."
    ),
    tech="{stranica}: <html> bez lang atributa",
)
def lang_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.lang is not None:
        return ok(lang_missing.spec)
    return finding(
        lang_missing.spec,
        ctx,
        evidence={"stranica": snapshot.home.final_url or snapshot.home.url, "lang_oznaka": 0},
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "i18n.lang.invalid",
    level=1,
    category="i18n",
    base_severity="medium",
    requires=["home"],
    description="Atribut lang postoji ali ne označava nijedan jezik.",
    threshold="lang ∈ {zxx, und, prazno} ili ne parsira kao BCP-47",
    message=(
        "Sajt je u kodu označen oznakom „{lang}”, koja ne označava nijedan jezik. "
        "Za pretraživače je to isto kao da oznake nema."
    ),
    tech='{stranica}: lang="{lang}" nije upotrebljiv BCP-47 kod',
)
def lang_invalid(snapshot: SiteSnapshot, ctx: Context):
    lang = snapshot.home.lang
    if lang is None or _lang_usable(lang):
        return ok(lang_invalid.spec)
    return finding(
        lang_invalid.spec,
        ctx,
        evidence={
            "stranica": snapshot.home.final_url or snapshot.home.url,
            "lang": lang,
            "duzina_koda": len(lang.strip()),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "i18n.lang.mismatch",
    level=1,
    category="i18n",
    base_severity="high",
    requires=["home"],
    description="Sadržaj je pouzdano srpski, a lang oznaka govori drugo.",
    threshold="sadržaj prepoznat kao sr (ćirilica > 30 % ili dijakritici > 0,5 %) uz lang koji ne počinje sa sr",
    message=(
        "Sadržaj sajta je na srpskom, ali je u kodu označen kao „{lang}”. Pretraživači ga "
        "zato nude pogrešnom tržištu, a čitači ekrana ga izgovaraju engleskim izgovorom."
    ),
    tech='{stranica}: lang="{lang}", sadržaj prepoznat kao {prepoznat_jezik} '
    "(ćirilica {cirilica_udeo}, dijakritici {dijakritici_udeo}, {duzina_teksta} znakova)",
)
def lang_mismatch(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    min_text = ctx.th("thresholds.i18n.min_text_length")
    if home.text_length < min_text:
        # Ujedno i signal za eskalaciju na nivo 2 (§6): sadržaj se verovatno crta iz JS-a.
        return unknown(
            lang_mismatch.spec,
            f"premalo teksta u sirovom HTML-u ({home.text_length} < {min_text} znakova)",
        )
    # Nedostajuću i neupotrebljivu oznaku pokrivaju druge dve provere; `zxx` mora
    # da padne u `invalid`, ne ovde (§12.4).
    if not _lang_usable(home.lang):
        return ok(lang_mismatch.spec)

    cyr_ratio = ctx.th("thresholds.i18n.cyrillic_ratio")
    dia_ratio = ctx.th("thresholds.i18n.diacritic_ratio")
    detected = detect_language(home.text_sample, cyr_ratio, dia_ratio)
    if detected != "sr" or home.lang.lower().startswith("sr"):
        return ok(lang_mismatch.spec)

    cyr = sum(1 for ch in home.text_sample if _is_cyrillic(ch))
    lat = sum(1 for ch in home.text_sample if ch.isalpha() and not _is_cyrillic(ch))
    dia = sum(1 for ch in home.text_sample if ch in DIJAKRITICI)
    return finding(
        lang_mismatch.spec,
        ctx,
        evidence={
            "stranica": home.final_url or home.url,
            "lang": home.lang,
            "prepoznat_jezik": detected,
            "cirilica_udeo": round(cyr / (cyr + lat), 4) if cyr + lat else 0.0,
            "dijakritici_udeo": round(dia / lat, 4) if lat else 0.0,
            "duzina_teksta": home.text_length,
        },
        urls=[home.final_url or home.url],
    )
