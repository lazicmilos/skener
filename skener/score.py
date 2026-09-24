"""Bodovanje, rangiranje i politika eskalacije (§6, §9). Čisto: bez I/O.

Sve troje su odluke nad već prikupljenim podacima, pa žive zajedno i testiraju se
zajedno. Eskalacija je ovde jer joj treba skor nivoa 1: kad kandidata ima više od
gornjeg limita, prolaze oni sa najvišim (§6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from skener.config import get, multiplier
from skener.models import (
    SEVERITY_ORDER,
    BrowserSnapshot,
    CheckResult,
    DomainReport,
    Finding,
    SiteSnapshot,
    Unknown,
)


def weigh(finding: Finding, industry: str, config: dict) -> float:
    """`weight = base_points × industry_multiplier[industry][category]` (§9.2).

    Ozbiljnost se posle množenja **ne menja** — menja se samo broj bodova (§3.5).
    """
    base = get(config, f"severity_points.{finding.severity}")
    return round(base * multiplier(config, industry, finding.category), 4)


def collect(results: Iterable[CheckResult]) -> tuple[list[Finding], list[Unknown]]:
    findings: list[Finding] = []
    unknowns: list[Unknown] = []
    for result in results:
        findings.extend(result.findings)
        if result.status == "unknown":
            unknowns.append(Unknown(check_id=result.check_id, reason=result.reason or ""))
    return findings, unknowns


def build_report(
    site: SiteSnapshot,
    results: Sequence[CheckResult],
    config: dict,
    *,
    browser: BrowserSnapshot | None = None,
    escalation_reasons: Sequence[str] = (),
) -> DomainReport:
    findings, unknowns = collect(results)
    for finding in findings:
        finding.weight = weigh(finding, site.industry, config)
    findings.sort(key=lambda f: (-f.weight, f.check_id))

    return DomainReport(
        domain=site.domain,
        industry=site.industry,
        final_url=site.entry.final_url if site.entry else None,
        status=_status(site, unknowns),
        level2_ran=browser is not None,
        escalation_reasons=list(escalation_reasons),
        findings=findings,
        unknowns=unknowns,
        total_score=round(sum(f.weight for f in findings), 4),
        max_finding_weight=max((f.weight for f in findings), default=0.0),
        scanned_at=site.fetched_at,
    )


def _status(site: SiteSnapshot, unknowns: Sequence[Unknown]) -> str:
    home = site.home
    if home is None or home.status != 200:
        return "failed"
    if unknowns or site.budget.exhausted:
        return "partial"
    return "scanned"


def rank(reports: Iterable[DomainReport]) -> list[DomainReport]:
    """§9.4: sajt sa jednom katastrofom je bolji lead od sajta sa deset sitnica.

    Primarni ključ je najteži pojedinačni nalaz; zbir samo razrešava izjednačenje.
    Rangiranje po zbiru bi Ariju stavilo iznad Mense, a Mensa ima najskuplji SEO
    problem koji postoji.
    """
    ordered = sorted(reports, key=lambda r: (-r.max_finding_weight, -r.total_score, r.domain))
    for position, report in enumerate(ordered, start=1):
        report.rank = position
    return ordered


# --------------------------------------------------------------------------- #
# Politika eskalacije na nivo 2 (§6)
# --------------------------------------------------------------------------- #
def escalation_reasons(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> list[str]:
    """Razlozi zbog kojih domen ide na nivo 2; prazna lista znači da ne ide.

    Prazan sirovi HTML **nije nalaz**, nego signal. Ako ga prijaviš kao nalaz,
    rekao si klijentu da nema h1 iako ga ima — samo ga ti nisi video (§6).
    """
    home = site.home
    if home is None or home.status != 200:
        return []

    reasons: list[str] = []
    text_limit = get(config, "escalation.empty_html_text_threshold")
    if home.text_length < text_limit:
        reasons.append(f"sirovi HTML ima {home.text_length} znakova teksta (< {text_limit})")
    if home.h1_count_raw == 0:
        reasons.append("sirovi HTML nema nijedan h1 — sadržaj se verovatno crta iz JS-a")

    findings, _ = collect(results)
    if any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings):
        reasons.append("ima bar jedan nalaz nivoa 1 ozbiljnosti ≥ medium")

    html_limit = get(config, "escalation.raw_html_bytes")
    if home.html_bytes > html_limit:
        reasons.append(f"HTML početne je {home.html_bytes} B (> {html_limit})")
    if any(f.check_id == "perf.compression.missing" for f in findings):
        reasons.append("HTML se ne šalje kompresovan")

    # Ovaj uslov zatvara rupu koju ostala četiri ostavljaju: sajt sa čistim SEO-om
    # i sporom stranicom inače nikad ne bi stigao na nivo 2 (§6, `cdei.rs`).
    slow = get(config, "escalation.slow_entry_ms")
    if site.entry and site.entry.elapsed_ms and site.entry.elapsed_ms > slow:
        reasons.append(f"početna odgovara za {site.entry.elapsed_ms} ms (> {slow})")
    return reasons


def level1_score(site: SiteSnapshot, results: Sequence[CheckResult], config: dict) -> float:
    findings, _ = collect(results)
    return round(sum(weigh(f, site.industry, config) for f in findings), 4)


def select_for_level2(
    candidates: Sequence[tuple[SiteSnapshot, Sequence[CheckResult]]], config: dict
) -> list[SiteSnapshot]:
    """Tvrd gornji limit (§6).

    Bez njega prvi prolaz nad 200 domena gde ih 180 ima bar jedan nalaz traje sat
    vremena i ti odustaneš od alata.
    """
    limit = get(config, "escalation.max_level2")

    def key(pair: tuple[SiteSnapshot, Sequence[CheckResult]]) -> tuple[bool, float, str]:
        site, results = pair
        findings, _ = collect(results)
        # Kandidat bez nalaza ≥ medium je kandidat samo zbog signala koje vidi browser
        # (prazan HTML, nema h1, spora početna). Nivo 2 mu je jedina šansa za pravi
        # nalaz; bez njega u izveštaju stoji kao „0 nalaza", a nije ni meren (BUG-005).
        # Zato ide prvi, pa tek onda ostali po skoru nivoa 1.
        jak = any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"] for f in findings)
        return (jak, -level1_score(site, results, config), site.domain)

    return [site for site, _ in sorted(candidates, key=key)[:limit]]


def analyze(
    site: SiteSnapshot,
    config: dict,
    *,
    browser: BrowserSnapshot | None = None,
    escalation: Sequence[str] = (),
) -> DomainReport:
    """Snapshoti → provere → bodovan izveštaj. Bez I/O, pa `recheck` ide bez mreže."""
    from skener.checks import registry

    registry.load_all()
    ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
    results = list(registry.run(1, site, ctx))
    if browser is not None:
        results.extend(registry.run(2, browser, ctx))
    return build_report(site, results, config, browser=browser, escalation_reasons=escalation)
