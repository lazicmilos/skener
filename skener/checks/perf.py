"""Provere performansi (§5, §7.3) i jedna QA provera koja se meri istim prolazom.

Pragovi su **stepenasti**: prijavljuje se jedan nalaz po `check_id`, sa najvišom
ozbiljnošću koja važi — ne tri nalaza za istu stranicu (§7.3).
"""

from __future__ import annotations

from skener.checks.registry import Context, check, finding, ok, unknown
from skener.models import SiteSnapshot

COMPRESSED = {"gzip", "br", "zstd", "deflate"}
BYTES_PER_MB = 1_000_000  # decimalni MB — 14 903 221 B = 14,9 MB, kako se i piše u mejlu


def _tier(value: float, tiers: dict[str, float]) -> str | None:
    """Najviša ozbiljnost čiji je prag prekoračen, ili `None`."""
    for severity in ("critical", "high", "medium"):
        if severity in tiers and value > tiers[severity]:
            return severity
    return None


def _seconds_on_mobile(mb: float, ctx: Context) -> float:
    """0,6 MB/s + režija. Pretpostavka mora da stoji u fusnoti izveštaja (§10.3)."""
    mb_per_s = ctx.th("thresholds.perf.mobile_speed_mbps") / 8
    return round(mb / mb_per_s + ctx.th("report.mobile_overhead_s"), 1)


# --------------------------------------------------------------------------- #
# Nivo 1
# --------------------------------------------------------------------------- #
@check(
    "perf.compression.missing",
    level=1,
    category="perf",
    base_severity="medium",
    requires=["home"],
    description="Server ne šalje HTML kompresovan.",
    threshold="content-encoding ∉ {gzip, br, zstd, deflate} i HTML > 50 kB",
    message=(
        "Server šalje stranicu nesažetu, iako bi sažimanje smanjilo prenos sa {kb} kB na "
        "otprilike četvrtinu. Na mobilnoj vezi to je sekunda i po razlike do prvog prikaza."
    ),
    tech="content-encoding={kodiranje}, html_bytes={bajtova} (dekodirano)",
)
def compression_missing(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    encoding = (home.headers.get("content-encoding") or "").lower().strip()
    min_bytes = ctx.th("thresholds.perf.compression_min_kb") * 1024
    if encoding in COMPRESSED or home.html_bytes <= min_bytes:
        return ok(compression_missing.spec)
    return finding(
        compression_missing.spec,
        ctx,
        evidence={
            "kodiranje": encoding or "nema",
            "bajtova": home.html_bytes,
            "kb": round(home.html_bytes / 1024),
        },
        urls=[home.final_url or home.url],
    )


@check(
    "perf.redirect.chain",
    level=1,
    category="perf",
    base_severity="low",
    requires=["entry_response"],
    description="Početna se otvara kroz niz preusmerenja.",
    threshold="broj skokova ≥ thresholds.perf.redirect_hops (3)",
    message=(
        "Otvaranje početne strane prolazi kroz {skokova} preusmerenja pre nego što se nešto "
        "prikaže. Svako od njih dodaje čekanje, najviše na mobilnoj vezi."
    ),
    tech="redirect_chain={skokova} skokova: {lanac}",
)
def redirect_chain(snapshot: SiteSnapshot, ctx: Context):
    chain = snapshot.entry.redirect_chain
    hops = max(len(chain) - 1, 0)
    if hops < ctx.th("thresholds.perf.redirect_hops"):
        return ok(redirect_chain.spec)
    return finding(
        redirect_chain.spec,
        ctx,
        evidence={"skokova": hops, "lanac": " → ".join(chain)},
        urls=chain[:1],
    )


@check(
    "perf.html.size",
    level=1,
    category="perf",
    base_severity="low",
    requires=["home"],
    description="Sam HTML dokument je prevelik.",
    threshold="html_bytes > thresholds.perf.html_size_kb (500 kB)",
    message=(
        "Sam kod početne strane teži {kb} kB, pre slika i skripti. Pretraživač mora sve to "
        "da pročita pre nego što išta nacrta."
    ),
    tech="html_bytes={bajtova} > {prag_kb} kB",
)
def html_size(snapshot: SiteSnapshot, ctx: Context):
    home = snapshot.home
    limit_kb = ctx.th("thresholds.perf.html_size_kb")
    if home.html_bytes <= limit_kb * 1024:
        return ok(html_size.spec)
    return finding(
        html_size.spec,
        ctx,
        evidence={"bajtova": home.html_bytes, "kb": round(home.html_bytes / 1024), "prag_kb": limit_kb},
        urls=[home.final_url or home.url],
    )


# --------------------------------------------------------------------------- #
# Nivo 2
# --------------------------------------------------------------------------- #
@check(
    "perf.page.weight",
    level=2,
    category="perf",
    base_severity="critical",
    requires=["network"],
    description="Ukupna težina početne strane.",
    threshold="> 1,5 MB medium · > 3 MB high · > 8 MB critical",
    message=(
        "Početna strana prenosi {mb} MB. Na prosečnoj mobilnoj vezi to je oko {sekundi} "
        "sekundi do prikaza; većina posetilaca ne čeka toliko."
    ),
    tech="total_bytes={bajtova} ({mb} MB), zahteva={zahteva}, nemereno={nemereno}, reached={reached}",
)
def page_weight(snapshot, ctx: Context):
    network = snapshot.network
    max_unmeasured = ctx.th("browser.max_unmeasured_responses")
    if network.unmeasured_responses > max_unmeasured:
        # Merenje u koje nemaš poverenja gore je od merenja kojeg nema (§7.2).
        return unknown(
            page_weight.spec,
            f"{network.unmeasured_responses} odgovora nije izmereno (prag {max_unmeasured})",
        )

    mb = network.total_bytes / BYTES_PER_MB
    severity = _tier(mb, ctx.th("thresholds.perf.page_weight_mb"))
    if severity is None:
        if snapshot.timing.reached == "timeout":
            return unknown(page_weight.spec, "učitavanje prekinuto pre kraja, izmereno je nepotpuno")
        return ok(page_weight.spec)
    return finding(
        page_weight.spec,
        ctx,
        severity=severity,
        evidence={
            "bajtova": network.total_bytes,
            "mb": round(mb, 1),
            "sekundi": _seconds_on_mobile(mb, ctx),
            "zahteva": network.request_count,
            "nemereno": network.unmeasured_responses,
            "reached": snapshot.timing.reached,
            "po_tipu": network.bytes_by_type,
        },
        urls=[snapshot.url],
    )


@check(
    "perf.request.count",
    level=2,
    category="perf",
    base_severity="high",
    requires=["network"],
    description="Broj mrežnih zahteva pri otvaranju početne.",
    threshold="> 100 medium · > 150 high",
    message=(
        "Otvaranje početne strane pokreće {zahteva} odvojenih preuzimanja. Na mobilnoj vezi "
        "svako od njih ima svoju cenu čekanja, nezavisno od veličine."
    ),
    tech="request_count={zahteva} (reached={reached})",
)
def request_count(snapshot, ctx: Context):
    count = snapshot.network.request_count
    severity = _tier(count, ctx.th("thresholds.perf.request_count"))
    if severity is None:
        if snapshot.timing.reached == "timeout":
            return unknown(request_count.spec, "učitavanje prekinuto pre kraja, izmereno je nepotpuno")
        return ok(request_count.spec)
    return finding(
        request_count.spec,
        ctx,
        severity=severity,
        evidence={"zahteva": count, "reached": snapshot.timing.reached},
        urls=[snapshot.url],
    )


@check(
    "perf.load.time",
    level=2,
    category="perf",
    base_severity="high",
    requires=["browser"],
    description="Vreme do potpunog učitavanja početne.",
    threshold="> 4 s medium · > 8 s high · prekid posle tvrdog limita = high",
    message=(
        "Početnoj strani treba {sekundi} sekundi da se do kraja učita. Posetilac koji dolazi "
        "sa telefona za to vreme najčešće odustane."
    ),
    tech="load_ms={load_ms}, reached={reached}",
)
def load_time(snapshot, ctx: Context):
    timing = snapshot.timing
    if timing.reached == "timeout":
        # Stranica koja ne stigne do `load` unutar tvrdog limita je merenje samo po sebi.
        limit_s = ctx.th("browser.timeout_s")
        return finding(
            load_time.spec,
            ctx,
            severity="high",
            evidence={"load_ms": None, "sekundi": limit_s, "reached": "timeout"},
            urls=[snapshot.url],
        )
    if timing.load_ms is None:
        return unknown(load_time.spec, "vreme učitavanja nije izmereno")
    severity = _tier(timing.load_ms, ctx.th("thresholds.perf.load_ms"))
    if severity is None:
        return ok(load_time.spec)
    return finding(
        load_time.spec,
        ctx,
        severity=severity,
        evidence={
            "load_ms": timing.load_ms,
            "sekundi": round(timing.load_ms / 1000, 1),
            "reached": timing.reached,
        },
        urls=[snapshot.url],
    )


@check(
    "perf.img.oversized",
    level=2,
    category="perf",
    base_severity="medium",
    requires=["browser"],
    description="Slike se šalju znatno veće nego što se prikazuju.",
    threshold="≥ 3 slike sa odnosom > 2,5 ili procenjen višak > 700 kB",
    message=(
        "Sajt šalje slike znatno veće nego što se prikazuju — oko {kb} kB nepotrebnog prenosa "
        "pri svakom učitavanju."
    ),
    tech="{broj_slika} slika sa ratio > {prag_odnosa}, procenjen višak {kb} kB, nemereno {nemereno}",
)
def img_oversized(snapshot, ctx: Context):
    dom = snapshot.dom
    oversized = dom.oversized_images
    waste_kb = round(sum(img.est_waste_kb for img in oversized))
    min_count = ctx.th("thresholds.perf.oversized_min_count")
    max_waste = ctx.th("thresholds.perf.oversized_waste_kb")

    if len(oversized) >= min_count or waste_kb > max_waste:
        return finding(
            img_oversized.spec,
            ctx,
            evidence={
                "broj_slika": len(oversized),
                "kb": waste_kb,
                "prag_odnosa": ctx.th("thresholds.perf.image_ratio"),
                "nemereno": dom.images_unmeasured,
                "najgora": oversized[0].src if oversized else None,
            },
            urls=[img.src for img in oversized[:5]],
        )
    # Bez ovoga ne znaš da li je „0 predimenzioniranih slika" nalaz ili neuspelo merenje (§3.3).
    if dom.images_unmeasured and dom.images_unmeasured >= dom.images_total / 2:
        return unknown(
            img_oversized.spec,
            f"{dom.images_unmeasured} od {dom.images_total} slika nije izmereno",
        )
    return ok(img_oversized.spec)


@check(
    "qa.console.errors",
    level=2,
    category="qa",
    base_severity="low",
    requires=["browser"],
    description="JavaScript greške u konzoli.",
    threshold="> thresholds.qa.console_errors (3)",
    message=(
        "Na početnoj strani se javlja {greske} JavaScript grešaka. Deo stranice zato može da "
        "ne radi kod dela posetilaca, najčešće na starijim telefonima."
    ),
    tech="console errors={greske}, warnings={upozorenja}",
)
def console_errors(snapshot, ctx: Context):
    # Slab prodajni signal — zato ostaje `low` i ne ide u mejl (§15, zamka 9).
    console = snapshot.console
    if console.errors <= ctx.th("thresholds.qa.console_errors"):
        return ok(console_errors.spec)
    return finding(
        console_errors.spec,
        ctx,
        evidence={
            "greske": console.errors,
            "upozorenja": console.warnings,
            "primer": console.samples[0] if console.samples else None,
        },
        urls=[snapshot.url],
    )
