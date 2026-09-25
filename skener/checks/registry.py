"""Registar provera (§2.4) i motor koji ga prolazi.

Provere se **ne pozivaju iz if-else lanca**. Svaka se registruje sa svojim
metapodacima, a motor samo prođe kroz registar — pa su lista provera, tabela u
README-u i `skener explain` jedan isti podatak, a ne tri koja se razilaze.

Pravilo koje se ne krši (§2.3): ovaj paket ne uvozi `httpx`, `playwright`, ni
`fetch.*` osim `fetch.urls`. Ako ti zatreba nešto sa mreže — fali ti polje u
snapshotu, dodaj polje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from skener.config import get
from skener.models import CheckResult, Finding

CheckFn = Callable[[Any, "Context"], CheckResult]


@dataclass
class Context:
    """Sve što provera sme da zna: ko je domen i koji su pragovi."""

    domain: str
    industry: str
    config: dict[str, Any]
    host_canonicalization: bool = False

    def th(self, dotted: str) -> Any:
        return get(self.config, dotted)


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    level: int
    category: str
    base_severity: str
    requires: tuple[str, ...]
    description: str
    threshold: str
    fn: CheckFn
    optional: bool = False


REGISTRY: dict[str, CheckSpec] = {}


def check(
    check_id: str,
    *,
    level: int,
    category: str,
    base_severity: str,
    description: str,
    threshold: str,
    requires: Iterable[str] = (),
    optional: bool = False,
) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        if check_id in REGISTRY:
            raise ValueError(f"duplikat check_id: {check_id}")
        spec = CheckSpec(
            check_id=check_id,
            level=level,
            category=category,
            base_severity=base_severity,
            requires=tuple(requires),
            description=description,
            threshold=threshold,
            fn=fn,
            optional=optional,
        )
        REGISTRY[check_id] = spec
        # Telo provere dohvata svoj spec preko `fn.spec` — bez traženja po registru.
        fn.spec = spec  # type: ignore[attr-defined]
        return fn

    return register


# --------------------------------------------------------------------------- #
# Konstruktori rezultata — jedini način na koji provera sme da odgovori
# --------------------------------------------------------------------------- #
def ok(spec: CheckSpec) -> CheckResult:
    return CheckResult(check_id=spec.check_id, status="ok")


def unknown(spec: CheckSpec, reason: str) -> CheckResult:
    """`unknown` bez razloga je bug (§3.4) — potpis to i ne dozvoljava."""
    return CheckResult(check_id=spec.check_id, status="unknown", reason=reason)


def finding(
    spec: CheckSpec,
    ctx: Context,
    *,
    evidence: dict[str, Any],
    urls: Iterable[str] = (),
    severity: str | None = None,
    variant: str | None = None,
) -> CheckResult:
    """Nalaz nosi dokaz, a rečenicu iz njega pravi `skener.messages` pri prikazu.

    To nije stil nego tvrdnja: ako rečenica za klijenta sadrži broj, taj broj
    nužno postoji u `evidence`. „Sajt je spor" tako ne može da prođe (§3.5).
    """
    return CheckResult(
        check_id=spec.check_id,
        status="finding",
        findings=[
            Finding(
                domain=ctx.domain,
                check_id=spec.check_id,
                level=spec.level,
                category=spec.category,
                severity=severity or spec.base_severity,
                evidence=evidence,
                evidence_urls=[u for u in urls if u],
                variant=variant,
            )
        ],
    )


# --------------------------------------------------------------------------- #
# Preduslovi: `requires` iz §2.4 — zašto provera ne može da se izvrši
# --------------------------------------------------------------------------- #
def _home_ok(snapshot: Any) -> bool:
    home = getattr(snapshot, "home", None)
    return bool(home and home.status == 200 and home.html_bytes)


REQUIREMENTS: dict[str, tuple[Callable[[Any], bool], str]] = {
    "entry": (
        lambda s: s.entry is not None,
        "početna strana nije ni pokušana (budžet potrošen pre nje)",
    ),
    "entry_response": (
        lambda s: s.entry is not None and s.entry.status is not None,
        "početna nije vratila nijedan odgovor (mrežna greška pre HTTP-a)",
    ),
    "home": (_home_ok, "početna strana nije uspešno dohvaćena"),
    "home_html": (
        lambda s: bool(s.home and s.home.raw_html),
        "sirovi HTML početne strane nije sačuvan",
    ),
    "pages": (
        lambda s: sum(1 for p in s.pages if p.status == 200) >= 3,
        "uzorak ima manje od 3 uspešno dohvaćene stranice",
    ),
    "robots": (
        lambda s: s.robots.status is not None,
        "zahtev za robots.txt nije izvršen (mrežna greška ili budžet)",
    ),
    "sitemap": (
        lambda s: s.sitemap.status is not None,
        "zahtev za sitemap nije izvršen (mrežna greška ili budžet)",
    ),
    "soft404": (
        lambda s: len(s.soft404.probes) == 2 and all(p.status is not None for p in s.soft404.probes),
        "obe sonde za lažni 404 nisu izvršene",
    ),
    "browser": (
        lambda s: s.status != "failed",
        "stranica nije otvorena u browseru",
    ),
    "network": (
        lambda s: s.status != "failed" and s.network.request_count > 0,
        "mrežni saobraćaj nije izmeren",
    ),
}


def unmet(spec: CheckSpec, snapshot: Any) -> str | None:
    for name in spec.requires:
        predicate, reason = REQUIREMENTS[name]
        try:
            if not predicate(snapshot):
                return reason
        except (AttributeError, TypeError):
            return reason
    return None


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
def specs_for(level: int, ctx: Context) -> list[CheckSpec]:
    return [
        spec
        for spec in sorted(REGISTRY.values(), key=lambda s: s.check_id)
        if spec.level == level and (not spec.optional or ctx.host_canonicalization)
    ]


def run(level: int, snapshot: Any, ctx: Context) -> list[CheckResult]:
    """Svaka provera u sopstvenom `try`: izuzetak nikad ne napušta domen (§8.2)."""
    results: list[CheckResult] = []
    for spec in specs_for(level, ctx):
        reason = unmet(spec, snapshot)
        if reason:
            results.append(unknown(spec, reason))
            continue
        try:
            results.append(spec.fn(snapshot, ctx))
        except Exception as exc:  # noqa: BLE001 — granica domena, namerno široka
            results.append(unknown(spec, f"provera je pukla: {type(exc).__name__}: {exc}"))
    return results


def load_all() -> None:
    """Uvozi module sa proverama da bi se dekoratori izvršili."""
    from skener.checks import a11y, i18n, infra, perf, seo, social  # noqa: F401
