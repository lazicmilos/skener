"""Open Graph provere (§5).

Hotelski i ugostiteljski link se deli u porukama i grupama; gost koji dobije golu
adresu bez slike i naslova ne klikne. Zato `social` na hotelu nosi množilac 1,5,
a na b2b 0,7 (§9.2).
"""

from __future__ import annotations

from skener.checks.registry import Context, check, finding, ok
from skener.models import SiteSnapshot


def _og_count(snapshot: SiteSnapshot) -> int:
    og = snapshot.home.og
    return sum(1 for value in (og.title, og.description, og.image, og.url) if value)


@check(
    "social.og.title.missing",
    level=1,
    category="social",
    base_severity="high",
    requires=["home"],
    description="Početna nema og:title.",
    threshold="nedostaje <meta property=og:title>",
    message=(
        "Kada neko podeli link sajta u poruci ili na Facebook-u, ne prikazuje se ni naslov "
        "ni slika — samo gola adresa. Gostima to izgleda kao sumnjiv link."
    ),
    tech="{stranica}: nedostaje og:title (ukupno og oznaka: {og_oznaka_ukupno})",
)
def og_title_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.title:
        return ok(og_title_missing.spec)
    return finding(
        og_title_missing.spec,
        ctx,
        evidence={
            "stranica": snapshot.home.final_url or snapshot.home.url,
            "og_oznaka_ukupno": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "social.og.description.missing",
    level=1,
    category="social",
    base_severity="medium",
    requires=["home"],
    description="Početna nema og:description.",
    threshold="nedostaje <meta property=og:description>",
    message=(
        "Kad se link sajta podeli, ispod naslova nema nijedne rečenice koja objašnjava šta "
        "sajt nudi. Onaj ko vidi link nema razlog da ga otvori."
    ),
    tech="{stranica}: nedostaje og:description (ukupno og oznaka: {og_oznaka_ukupno})",
)
def og_description_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.description:
        return ok(og_description_missing.spec)
    return finding(
        og_description_missing.spec,
        ctx,
        evidence={
            "stranica": snapshot.home.final_url or snapshot.home.url,
            "og_oznaka_ukupno": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )


@check(
    "social.og.image.missing",
    level=1,
    category="social",
    base_severity="medium",
    requires=["home"],
    description="Početna nema og:image.",
    threshold="nedostaje <meta property=og:image>",
    message=(
        "Podeljen link sajta nema sliku. U Viber i WhatsApp grupama, gde se preporuke i "
        "šalju, link bez slike prolazi neprimećeno pored onih koji je imaju."
    ),
    tech="{stranica}: nedostaje og:image (ukupno og oznaka: {og_oznaka_ukupno})",
)
def og_image_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.home.og.image:
        return ok(og_image_missing.spec)
    return finding(
        og_image_missing.spec,
        ctx,
        evidence={
            "stranica": snapshot.home.final_url or snapshot.home.url,
            "og_oznaka_ukupno": _og_count(snapshot),
        },
        urls=[snapshot.home.final_url or snapshot.home.url],
    )
