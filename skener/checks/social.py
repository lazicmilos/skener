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
        "Kada neko podeli link sajta u poruci ili na Facebook-u, nema pripremljenog naslova "
        "za pregled linka, pa platforme uzimaju običan naslov strane ili samu adresu."
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
        "Kad se link sajta podeli, platforme nemaju pripremljen opis, pa same biraju tekst sa "
        "strane ili ne prikazuju nijedan."
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
        "Podeljen link sajta nema pripremljenu sliku. U Viber i WhatsApp grupama, gde se "
        "preporuke često šalju, link bez slike lako prođe neprimećeno."
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
