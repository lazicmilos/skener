"""Infrastrukturne provere (§5, §5.2)."""

from __future__ import annotations

from difflib import SequenceMatcher

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

SIMILARITY_CHARS = 2000


@check(
    "infra.sitemap.missing",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["sitemap"],
    description="Nema sitemap.xml, ili postoji ali je prazan.",
    threshold="status ≠ 200, ili 200 sa 0 URL-ova",
    message=(
        "Sajt nema mapu stranica. Google mora sam da pogađa koje stranice postoje, pa nove i "
        "dublje stranice ume da pronađe tek posle više nedelja — ili nikad."
    ),
    tech="sitemap status={status}, urls={broj_urlova}",
)
def sitemap_missing(snapshot: SiteSnapshot, ctx: Context):
    info = snapshot.sitemap
    if info.status == 200 and info.urls:
        return ok(sitemap_missing.spec)
    return finding(
        sitemap_missing.spec,
        ctx,
        evidence={"status": info.status, "broj_urlova": len(info.urls)},
        urls=[info.url] if info.url else [],
    )


@check(
    "infra.robots.missing",
    level=1,
    category="infra",
    base_severity="low",
    requires=["robots"],
    description="Nema robots.txt.",
    threshold="status ≠ 200",
    message=(
        "Sajt nema robots.txt. Ništa se time ne lomi, ali je to fajl koji svaki pretraživač "
        "prvo traži, i njegov izostanak je znak da se sajt nije podešavao za pretragu."
    ),
    tech="robots.txt status={status}",
)
def robots_missing(snapshot: SiteSnapshot, ctx: Context):
    if snapshot.robots.status == 200:
        return ok(robots_missing.spec)
    return finding(
        robots_missing.spec,
        ctx,
        evidence={"status": snapshot.robots.status},
    )


@check(
    "infra.soft404",
    level=1,
    category="infra",
    base_severity="high",
    requires=["soft404"],
    description="Nepostojeća adresa vraća 200 umesto 404.",
    threshold="obe sonde vraćaju konačni status 200 (§5.2)",
    message=(
        "Na nepostojeću adresu sajt vraća običnu stranicu umesto poruke o grešci — obe "
        "proverene izmišljene adrese vratile su status {status}. Google zbog toga može da "
        "indeksira neograničen broj praznih adresa."
    ),
    tech="obe sonde status={status}, sličnost sa početnom {slicnost}",
)
def soft404(snapshot: SiteSnapshot, ctx: Context):
    probes = snapshot.soft404.probes
    statuses = [p.status for p in probes]
    if not all(s == 200 for s in statuses):
        # Jedna sonda 200 a druga 404 → `ok`, ne nalaz (§5.2).
        return ok(soft404.spec)

    home = snapshot.home
    similarity = 0.0
    if home and home.text_sample:
        similarity = max(
            SequenceMatcher(
                None, home.text_sample[:SIMILARITY_CHARS], p.text_sample[:SIMILARITY_CHARS]
            ).ratio()
            for p in probes
        )
    evidence = {
        "status": 200,
        "broj_sondi": len(probes),
        "slicnost": round(similarity, 3),
        "tvrd_dokaz": similarity >= ctx.th("thresholds.soft404.text_similarity"),
    }
    return finding(soft404.spec, ctx, evidence=evidence, urls=[p.url for p in probes])


@check(
    "infra.tls.invalid",
    level=1,
    category="infra",
    base_severity="high",
    requires=["entry"],
    description="Sertifikat je nevalidan ili istekao.",
    threshold="TLS provera odbila sertifikat",
    message=(
        "Sertifikat sajta nije valjan, pa pretraživač posetiocima prikazuje crveno upozorenje "
        "pre nego što uđu na sajt. Većina se na toj strani vrati nazad."
    ),
    tech="TLS greška: {greska}",
)
def tls_invalid(snapshot: SiteSnapshot, ctx: Context):
    tls = snapshot.entry.tls
    if tls.valid:
        return ok(tls_invalid.spec)
    return finding(
        tls_invalid.spec,
        ctx,
        evidence={"greska": tls.error or "nepoznata", "valid": 0},
        urls=[snapshot.entry.requested_url],
    )


@check(
    "infra.dns.unresolved",
    level=1,
    category="infra",
    base_severity="critical",
    requires=["entry"],
    description="Domen se ne razrešava preko DNS-a.",
    threshold="DNS upit nije vratio adresu",
    message=(
        "Domen se uopšte ne otvara — ne postoji zapis koji ga povezuje sa serverom. "
        "Za posetioca i za Google sajt trenutno ne postoji."
    ),
    tech="DNS ne razrešava: {detalj}",
)
def dns_unresolved(snapshot: SiteSnapshot, ctx: Context):
    entry = snapshot.entry
    if entry.error_kind != "dns":
        return ok(dns_unresolved.spec)
    return finding(
        dns_unresolved.spec,
        ctx,
        evidence={"detalj": entry.error_detail or "nepoznato", "razresenih_adresa": 0},
        urls=[entry.requested_url],
    )
