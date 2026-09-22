"""Komandna linija i orkestracija faza (§11). Sam ne dodiruje ni mrežu ni logiku."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from skener import __version__, store
from skener.checks import registry
from skener.config import ConfigError, load_config
from skener.models import INDUSTRIES, DomainInput, SiteSnapshot
from skener.report import csv_out, html_out
from skener.score import analyze, escalation_reasons, rank, select_for_level2

log = logging.getLogger("skener")

PRIMER = """
primeri:
  skener scan domains.example.csv --out izvestaj/
  skener scan domains.csv --level 1 --concurrency 4 --only mensa.rs
  skener recheck snapshots/ --out izvestaj/        # bez mreže, za kalibraciju pragova
  skener record domains.example.csv --out tests/fixtures/
  skener explain seo.canonical.duplicate
  skener explain --all --markdown > provere.md
"""


# --------------------------------------------------------------------------- #
# Logovanje (§11.3): JSON linije na stderr, polje `domain` u svakom zapisu
# --------------------------------------------------------------------------- #
class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "domain": getattr(record, "domain", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class OnlyDomain(logging.Filter):
    """`--debug-domain`: kad se jedan sajt ponaša čudno, ne želiš log od 200 domena."""

    def __init__(self, domain: str) -> None:
        super().__init__()
        self.domain = domain

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.DEBUG:
            return True
        return getattr(record, "domain", None) == self.domain


def setup_logging(debug_domain: str | None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLines())
    if debug_domain:
        handler.addFilter(OnlyDomain(debug_domain))
    root = logging.getLogger("skener")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug_domain else logging.INFO)


# --------------------------------------------------------------------------- #
# Ulaz
# --------------------------------------------------------------------------- #
def read_domains(path: Path, only: Sequence[str] = ()) -> list[DomainInput]:
    """CSV sa zaglavljem, ne gola lista domena (§4.1)."""
    rows: list[DomainInput] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "domain" not in reader.fieldnames:
            raise SystemExit(f"{path}: nedostaje kolona `domain` u zaglavlju (§4.1)")
        for row in reader:
            domain = (row.get("domain") or "").strip()
            if not domain or domain.startswith("#"):
                continue
            industry = (row.get("industry") or "").strip().lower() or "ostalo"
            if industry not in INDUSTRIES:
                log.warning(
                    "nepoznata delatnost %r, koristim `ostalo`", industry, extra={"domain": domain}
                )
                industry = "ostalo"
            rows.append(DomainInput(domain=domain, industry=industry, note=(row.get("note") or "").strip()))
    if only:
        wanted = {d.lower() for d in only}
        rows = [r for r in rows if r.domain.lower() in wanted]
    if not rows:
        raise SystemExit(f"{path}: nijedan domen nije učitan")
    return rows


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def cmd_scan(args: argparse.Namespace) -> int:
    from skener.fetch.http import scan_domains

    config = load_config(args.config)
    if args.concurrency:
        config["http"]["concurrency"] = args.concurrency
    if args.max_level2 is not None:
        config["escalation"]["max_level2"] = args.max_level2

    targets = read_domains(Path(args.domains), args.only)
    snapshots_dir = Path(args.snapshots or Path(args.out) / "snapshots")
    started = time.monotonic()

    log.info("nivo 1: %d domena", len(targets))
    sites = asyncio.run(scan_domains(targets, config, snapshot_dir=snapshots_dir))

    browsers, reasons = _run_level2(sites, config, args, snapshots_dir)
    reports = rank(
        [
            analyze(site, config, browser=browsers.get(site.domain), escalation=reasons.get(site.domain, []))
            for site in sites
        ]
    )
    _emit(reports, config, args, duration_s=time.monotonic() - started)
    return 0


def _run_level2(
    sites: Sequence[SiteSnapshot], config: dict, args: argparse.Namespace, snapshots_dir: Path
) -> tuple[dict, dict[str, list[str]]]:
    """Eskalacija (§6) pa nivo 2 nad izabranima; vraća i razloge za izveštaj."""
    if args.level == "1":
        return {}, {}

    registry.load_all()
    candidates: list[tuple[SiteSnapshot, list]] = []
    reasons: dict[str, list[str]] = {}
    for site in sites:
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        results = registry.run(1, site, ctx)
        why = escalation_reasons(site, results, config)
        if why or args.level == "2":
            candidates.append((site, results))
            reasons[site.domain] = why or ["izričito traženo preko --level 2"]

    chosen = select_for_level2(candidates, config)
    log.info(
        "nivo 2: %d kandidata, %d prolazi, %d preko limita",
        len(candidates),
        len(chosen),
        len(candidates) - len(chosen),
    )
    if not chosen:
        return {}, reasons

    try:
        from skener.fetch.browser import capture_all
    except ImportError:
        log.error("Playwright nije instaliran; nivo 2 se preskače (pip install 'skener[browser]')")
        return {}, reasons

    return asyncio.run(capture_all(chosen, config, snapshot_dir=snapshots_dir)), reasons


def _emit(reports, config, args, duration_s: float | None = None) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}

    if "csv" in formats:
        csv_out.write_findings(out / "findings.csv", reports, bom=args.csv_bom)
        csv_out.write_summary(out / "summary.csv", reports, bom=args.csv_bom)
    if "html" in formats:
        html_out.write(out / "index.html", reports, config, duration_s=duration_s)

    nalaza = sum(len(r.findings) for r in reports)
    print(f"\n{len(reports)} domena · {nalaza} nalaza · izlaz u {out}/", file=sys.stderr)
    for report in reports[:10]:
        top = report.findings[0].check_id if report.findings else "—"
        print(
            f"  {report.rank:>3}. {report.domain:<28} skor {report.total_score:>7.1f}"
            f"  najteži {report.max_finding_weight:>5.1f}  {top}",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- #
# recheck — glavno oruđe pri kalibraciji (§11.1)
# --------------------------------------------------------------------------- #
def cmd_recheck(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    started = time.monotonic()
    reports = []
    for site, browser in store.read_all(Path(args.snapshots)):
        registry.load_all()
        ctx = registry.Context(domain=site.domain, industry=site.industry, config=config)
        reasons = escalation_reasons(site, registry.run(1, site, ctx), config)
        reports.append(analyze(site, config, browser=browser, escalation=reasons))
    if not reports:
        raise SystemExit(f"{args.snapshots}: nijedan snapshot nije pronađen")
    _emit(rank(reports), config, args, duration_s=time.monotonic() - started)
    return 0


# --------------------------------------------------------------------------- #
# record — snima fixture-e (§12.2)
# --------------------------------------------------------------------------- #
def cmd_record(args: argparse.Namespace) -> int:
    from skener.fetch.http import scan_domains

    config = load_config(args.config)
    targets = read_domains(Path(args.domains), args.only)
    out = Path(args.out)
    sites = asyncio.run(scan_domains(targets, config))

    for site in sites:
        # Bez sirovog HTML-a ostalih strana, inače repo naraste (§12.2).
        for page in site.pages[1:]:
            page.raw_html = None
        store.write_site(out, site, compress=True)

    if args.level != "1":
        try:
            from skener.fetch.browser import capture_all
        except ImportError:
            log.error("Playwright nije instaliran; snimam samo nivo 1")
        else:
            for snapshot in asyncio.run(capture_all(sites, config)).values():
                store.write_browser(out, snapshot, compress=True)

    print(f"snimljeno {len(sites)} snapshota u {out}/", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# explain — izveštaj upotrebljiv za nekog ko nisi ti (§11.1)
# --------------------------------------------------------------------------- #
def cmd_explain(args: argparse.Namespace) -> int:
    registry.load_all()
    specs = sorted(registry.REGISTRY.values(), key=lambda s: (s.level, s.check_id))

    if args.all:
        if args.markdown:
            print("| `check_id` | Nivo | Kategorija | Ozbiljnost | Prag |")
            print("|---|---|---|---|---|")
            for spec in specs:
                print(
                    f"| `{spec.check_id}` | {spec.level} | {spec.category} | "
                    f"{spec.base_severity} | {spec.threshold} |"
                )
        else:
            for spec in specs:
                print(f"{spec.check_id:32} nivo {spec.level}  {spec.base_severity:8} {spec.threshold}")
        return 0

    spec = registry.REGISTRY.get(args.check_id)
    if spec is None:
        blizu = [s.check_id for s in specs if args.check_id in s.check_id]
        raise SystemExit(
            f"nepoznata provera: {args.check_id}"
            + (f"\nda li si mislio: {', '.join(blizu)}" if blizu else "\nsve: skener explain --all")
        )

    print(f"{spec.check_id}\n{'=' * len(spec.check_id)}")
    print(f"nivo:        {spec.level}")
    print(f"kategorija:  {spec.category}")
    print(f"ozbiljnost:  {spec.base_severity}")
    print(f"prag:        {spec.threshold}")
    print(f"traži:       {', '.join(spec.requires) or '—'}")
    print(f"\n{spec.description}\n")
    print("rečenica za klijenta:")
    print(f"  {spec.message_template}")
    print("\ntehnička formulacija:")
    print(f"  {spec.tech_template}")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skener",
        description="Rangira domene po tome koji zaslužuju pun ručni audit. Čita, nikad ne piše.",
        epilog=PRIMER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"skener {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--config", metavar="FILE", help="TOML koji se spaja preko skener.toml")
        sub.add_argument("--out", default="out", metavar="DIR", help="gde idu izveštaji (podrazumevano: out)")
        sub.add_argument(
            "--format", default="html,csv", help="html, csv ili oba (podrazumevano: html,csv)"
        )
        sub.add_argument("--csv-bom", action="store_true", help="UTF-8 sa BOM-om, za Excel")
        sub.add_argument("--debug-domain", metavar="DOMAIN", help="DEBUG log samo za taj domen")

    scan = subparsers.add_parser("scan", help="pun prolaz nad listom domena")
    scan.add_argument("domains", metavar="DOMAINS.csv", help="CSV sa kolonama domain,industry,note")
    scan.add_argument("--level", choices=["1", "2", "auto"], default="auto", help="podrazumevano: auto")
    scan.add_argument("--concurrency", type=int, metavar="N", help="globalni semafor (podrazumevano 8)")
    scan.add_argument("--max-level2", type=int, metavar="N", help="gornji limit za nivo 2 (60)")
    scan.add_argument(
        "--snapshots", metavar="DIR", help="gde se pišu snapshoti (podrazumevano: OUT/snapshots)"
    )
    scan.add_argument(
        "--only", action="append", default=[], metavar="DOMAIN", help="samo ovaj domen; može više puta"
    )
    add_common(scan)
    scan.set_defaults(func=cmd_scan)

    recheck = subparsers.add_parser(
        "recheck", help="ponovo pokreće provere nad sačuvanim snapshotima, bez mreže"
    )
    recheck.add_argument("snapshots", metavar="SNAPSHOTS_DIR")
    add_common(recheck)
    recheck.set_defaults(func=cmd_recheck)

    record = subparsers.add_parser("record", help="snima snapshote kao fixture-e")
    record.add_argument("domains", metavar="DOMAINS.csv")
    record.add_argument("--out", required=True, metavar="DIR")
    record.add_argument("--level", choices=["1", "2", "auto"], default="auto")
    record.add_argument("--only", action="append", default=[], metavar="DOMAIN")
    record.add_argument("--config", metavar="FILE")
    record.add_argument("--debug-domain", metavar="DOMAIN")
    record.set_defaults(func=cmd_record)

    explain = subparsers.add_parser("explain", help="šta provera radi, koji joj je prag")
    explain.add_argument("check_id", nargs="?", metavar="CHECK_ID")
    explain.add_argument("--all", action="store_true", help="sve provere")
    explain.add_argument("--markdown", action="store_true", help="tabela za README (uz --all)")
    explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "explain" and not args.all and not args.check_id:
        parser.error("navedi CHECK_ID ili --all")
    setup_logging(getattr(args, "debug_domain", None))
    try:
        return args.func(args)
    except ConfigError as exc:
        raise SystemExit(f"greška u konfiguraciji: {exc}") from exc
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
