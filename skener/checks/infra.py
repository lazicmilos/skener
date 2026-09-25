"""Infrastrukturne provere (§5, §5.2)."""

from __future__ import annotations

from difflib import SequenceMatcher

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

SIMILARITY_CHARS = 2000
# Samo ovi statusi tvrde da nečega nema. 401, 403, 429 i 5xx znače da je pristup
# odbijen ili da server ne radi: tada ne znamo, pa je rezultat `unknown` (BUG-003).
NE_POSTOJI = frozenset({404, 410})


@check(
    "infra.sitemap.missing",
    level=1,
    category="infra",
    base_severity="medium",
    requires=["sitemap"],
    description="Nema sitemap.xml, ili postoji ali je prazan.",
    threshold="status 404 ili 410, ili 200 sa 0 URL-ova; ostali statusi → unknown",
)
def sitemap_missing(snapshot: SiteSnapshot, ctx: Context):
    info = snapshot.sitemap
    if info.status == 200 and info.urls:
        return ok(sitemap_missing.spec)
    if info.status != 200 and info.status not in NE_POSTOJI:
        return unknown(
            sitemap_missing.spec,
            f"server je na sitemap odgovorio statusom {info.status}; iz toga se ne vidi da li postoji",
        )
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
    threshold="status 404 ili 410; ostali statusi osim 200 → unknown",
)
def robots_missing(snapshot: SiteSnapshot, ctx: Context):
    status = snapshot.robots.status
    if status == 200:
        return ok(robots_missing.spec)
    if status not in NE_POSTOJI:
        return unknown(
            robots_missing.spec,
            f"server je na robots.txt odgovorio statusom {status}; iz toga se ne vidi da li postoji",
        )
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
    threshold="obe sonde vraćaju konačni status 200 (§5.2); status van {200, 404, 410} → unknown",
)
def soft404(snapshot: SiteSnapshot, ctx: Context):
    probes = snapshot.soft404.probes
    statuses = [p.status for p in probes]
    if not all(s == 200 for s in statuses):
        odbijene = [s for s in statuses if s != 200 and s not in NE_POSTOJI]
        if odbijene:
            return unknown(
                soft404.spec,
                f"sonde su dobile status {', '.join(map(str, odbijene))}; iz toga se ne vidi "
                "kako sajt odgovara na nepostojeću adresu",
            )
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
)
def tls_invalid(snapshot: SiteSnapshot, ctx: Context):
    entry = snapshot.entry
    tls = entry.tls
    if tls.valid:
        # Veza koja nije ni uspostavljena ne dokazuje da je sertifikat ispravan.
        # `ok` bi ovde bio tvrdnja koju nismo proverili (§3.4).
        if entry.status is None:
            return unknown(
                tls_invalid.spec,
                f"veza nije uspostavljena ({entry.error_kind or 'nepoznato'}), sertifikat nije proveren",
            )
        # Https nije uspeo, pa je sajt dohvaćen preko http-a: sertifikat nije ni viđen (BUG-004).
        https = next((e for e in snapshot.errors if e.stage == "entry"), None)
        if https is not None and entry.requested_url.startswith("http://"):
            return unknown(
                tls_invalid.spec,
                f"https nije uspeo ({https.kind}: {https.detail[:120]}); sajt je dohvaćen preko "
                "http-a, sertifikat nije proveren",
            )
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
