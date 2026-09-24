"""SEO provere (§5, §7.3)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.checks.srpski import sa_brojem
from skener.fetch.urls import collapse_ws, path_group
from skener.models import PageSnapshot, SiteSnapshot


def _duplicates(
    snapshot: SiteSnapshot, value_of: Callable[[PageSnapshot], str | None], min_pages: int
) -> tuple[str, list[PageSnapshot], set[str]] | None:
    """Najveća grupa stranica sa identičnom vrednošću, ako prelazi prag.

    Traži se ≥ `min_pages` stranica iz ≥ `min_pages` **različitih** grupa putanja
    (§5). Zahtev za različitim grupama je ono što čuva U4: osam blog postova sa
    istim naslovom šablona nije isto što i ceo sajt koji se predstavlja kao jedna
    stranica.
    """
    buckets: dict[str, list[PageSnapshot]] = defaultdict(list)
    for page in snapshot.pages:
        if page.status != 200:
            continue
        value = value_of(page)
        if value:
            buckets[value].append(page)

    for value, pages in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        groups = {path_group(p.final_url or p.url) for p in pages}
        if len(pages) >= min_pages and len(groups) >= min_pages:
            return value, pages, groups
    return None


def _sample_note(snapshot: SiteSnapshot) -> str:
    """Uzorak iz linkova je manje pouzdan od uzorka iz sitemapa (§4.4)."""
    return "sitemap" if snapshot.sample_source == "sitemap" else "interni linkovi sa početne"


# --------------------------------------------------------------------------- #
# canonical
# --------------------------------------------------------------------------- #
@check(
    "seo.canonical.missing",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home"],
    description="Početna strana nema <link rel=canonical>.",
    threshold="nema oznake na početnoj",
    message=(
        "Početna strana ne govori Google-u koja joj je zvanična adresa. Kad isti sadržaj "
        "postoji na više adresa (sa www i bez, sa parametrima iz reklama), Google sam bira "
        "koju će prikazati — i ume da izabere pogrešnu."
    ),
    tech="{stranica}: nedostaje <link rel=canonical>",
)
def canonical_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    if home.canonical:
        return ok(canonical_missing.spec)
    return finding(
        canonical_missing.spec,
        ctx,
        evidence={"stranica": home.final_url or home.url, "broj_canonical_oznaka": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.canonical.duplicate",
    level=1,
    category="seo",
    base_severity="critical",
    requires=["pages"],
    description="Više stranica iz različitih delova sajta prijavljuje isti canonical.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim canonical-om",
    message=(
        "Više proverenih stranica sajta ({stranica}) prijavljuje Google-u istu adresu kao "
        "zvaničnu ({canonical}). Google ih zato može smatrati kopijama jedne stranice i "
        "izostaviti iz pretrage."
    ),
    tech=(
        "canonical_normalized == {canonical} na {stranica} stranica "
        "iz {grupa_putanja} grupa putanja (uzorak: {uzorak})"
    ),
)
def canonical_duplicate(snapshot: SiteSnapshot, ctx: Context):
    min_pages = ctx.th("thresholds.seo.duplicate_min_pages")
    hit = _duplicates(snapshot, lambda p: p.canonical_normalized, min_pages)
    if not hit:
        return ok(canonical_duplicate.spec)
    value, pages, groups = hit
    return finding(
        canonical_duplicate.spec,
        ctx,
        evidence={
            "canonical": value,
            "stranica": len(pages),
            "n": len(pages) - 1,
            "grupa_putanja": len(groups),
            "uzorak": _sample_note(snapshot),
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# title
# --------------------------------------------------------------------------- #
@check(
    "seo.title.missing",
    level=1,
    category="seo",
    base_severity="high",
    requires=["home"],
    description="Početna strana nema <title> ili je prazan.",
    threshold="prazan ili nepostojeći <title>",
    message=(
        "Početna strana nema naslov. U kartici pretraživača zato stoji goli deo adrese, a "
        "Google u rezultatima sam smišlja naslov iz sadržaja strane."
    ),
    tech="{stranica}: <title> prazan ili nedostaje (dužina {duzina_naslova})",
)
def title_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    title = collapse_ws(home.title)
    if title:
        return ok(title_missing.spec)
    return finding(
        title_missing.spec,
        ctx,
        evidence={"stranica": home.final_url or home.url, "duzina_naslova": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.title.duplicate",
    level=1,
    category="seo",
    base_severity="high",
    requires=["pages"],
    description="Više stranica iz različitih delova sajta ima identičan naslov.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim naslovom",
    message=(
        "Različite stranice sajta imaju isti naslov („{naslov}”). U Google rezultatima "
        "izgledaju kao {kopije} iste stranice, pa Google teže bira koju da prikaže."
    ),
    tech="identičan normalizovan <title> na {stranica} stranica iz {grupa_putanja} grupa putanja",
)
def title_duplicate(snapshot: SiteSnapshot, ctx: Context):
    hit = _duplicates(snapshot, lambda p: collapse_ws(p.title), ctx.th("thresholds.seo.duplicate_min_pages"))
    if not hit:
        return ok(title_duplicate.spec)
    value, pages, groups = hit
    return finding(
        title_duplicate.spec,
        ctx,
        evidence={
            "naslov": value,
            "kopije": sa_brojem(len(pages), "kopija", "kopije", "kopija"),
            "stranica": len(pages),
            "grupa_putanja": len(groups),
            "uzorak": _sample_note(snapshot),
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# description
# --------------------------------------------------------------------------- #
@check(
    "seo.description.missing",
    level=1,
    category="seo",
    base_severity="medium",
    requires=["home"],
    description="Početna strana nema <meta name=description>.",
    threshold="prazan ili nepostojeći meta opis",
    message=(
        "Početna strana nema kratak opis za Google. Google tada sam bira tekst sa strane za "
        "prikaz ispod naslova, a to ume da bude deo menija ili obaveštenja o kolačićima."
    ),
    tech="{stranica}: nedostaje <meta name=description> (dužina {duzina_opisa})",
)
def description_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    if collapse_ws(home.meta_description):
        return ok(description_missing.spec)
    return finding(
        description_missing.spec,
        ctx,
        evidence={"stranica": home.final_url or home.url, "duzina_opisa": 0},
        urls=[home.final_url or home.url],
    )


@check(
    "seo.description.duplicate",
    level=1,
    category="seo",
    base_severity="medium",
    requires=["pages"],
    description="Više stranica iz različitih delova sajta ima identičan meta opis.",
    threshold="≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim opisom",
    message=(
        "Različite stranice sajta imaju isti opis u Google rezultatima. Posetilac iz pretrage "
        "zato ne vidi razliku između {stranice}."
    ),
    tech="identičan normalizovan meta opis na {stranica} stranica iz {grupa_putanja} grupa putanja",
)
def description_duplicate(snapshot: SiteSnapshot, ctx: Context):
    hit = _duplicates(
        snapshot, lambda p: collapse_ws(p.meta_description), ctx.th("thresholds.seo.duplicate_min_pages")
    )
    if not hit:
        return ok(description_duplicate.spec)
    value, pages, groups = hit
    return finding(
        description_duplicate.spec,
        ctx,
        evidence={
            "opis": value,
            "stranice": sa_brojem(len(pages), "stranice", "stranice", "stranica"),
            "stranica": len(pages),
            "grupa_putanja": len(groups),
            "uzorak": _sample_note(snapshot),
        },
        urls=[p.final_url or p.url for p in pages],
    )


# --------------------------------------------------------------------------- #
# h1 — nivo 2, jer sirovi HTML ume da bude prazan a sadržaj iz JS-a (§6)
# --------------------------------------------------------------------------- #
@check(
    "seo.h1.missing",
    level=2,
    category="seo",
    base_severity="high",
    requires=["browser"],
    description="Nacrtana stranica nema nijedan <h1>.",
    threshold="h1_count == 0 posle učitavanja u browseru",
    message=(
        "Stranica nema glavni naslov (h1). Naslovi su jedan od signala po kojima Google "
        "razume o čemu je strana, a korisnici čitača ekrana se po njima kreću kroz stranicu."
    ),
    tech="h1_count == {h1_count} (mereno u browseru, reached={reached})",
)
def h1_missing(snapshot, ctx: Context):
    if snapshot.dom.h1_count > 0:
        return ok(h1_missing.spec)
    if snapshot.timing.reached == "timeout":
        return unknown(h1_missing.spec, "stranica nije dovršila učitavanje, h1 može da stigne kasnije")
    return finding(
        h1_missing.spec,
        ctx,
        evidence={"h1_count": snapshot.dom.h1_count, "reached": snapshot.timing.reached},
        urls=[snapshot.url],
    )


@check(
    "seo.h1.multiple",
    level=2,
    category="seo",
    base_severity="low",
    requires=["browser"],
    description="Stranica ima previše <h1> naslova.",
    threshold="h1_count > thresholds.seo.h1_multiple (3)",
    message=(
        "Stranica ima {naslovi} (h1) umesto jednog. Korisnicima čitača ekrana "
        "je tada teže da prepoznaju glavnu temu strane."
    ),
    tech="h1_count == {h1_count} > {prag}",
)
def h1_multiple(snapshot, ctx: Context):
    limit = ctx.th("thresholds.seo.h1_multiple")
    if snapshot.dom.h1_count <= limit:
        return ok(h1_multiple.spec)
    return finding(
        h1_multiple.spec,
        ctx,
        evidence={
            "h1_count": snapshot.dom.h1_count,
            "naslovi": sa_brojem(snapshot.dom.h1_count, "glavni naslov", "glavna naslova", "glavnih naslova"),
            "prag": limit,
        },
        urls=[snapshot.url],
    )
