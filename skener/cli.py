"""Komandna linija (§11): argumenti, ulazni CSV, logovanje i izveštaji.

Prolaz vodi `skener.pipeline`; CLI ne dodiruje ni mrežu ni logiku.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from skener import __version__, pipeline
from skener.checks import registry
from skener.config import ConfigError, load_config
from skener.inputs import InputError
from skener.models import INDUSTRIES, DomainInput, Event, ScanResult
from skener.report import csv_out, html_out

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
    # „Z" u vremenu tvrdi UTC; podrazumevano je lokalno vreme, pa bi van Docker-a svaki
    # red bio pomeren za vremensku zonu mašine (BUG-012).
    converter = time.gmtime

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


FAZE = {"level1": "nivo 1", "level2": "nivo 2"}


def log_event(event: Event) -> None:
    """Brojač „43/200" za prolaz koji traje minutima. `recheck` traje sekundu i ne treba mu."""
    if event.kind == "domain_finished" and event.phase in FAZE:
        faza = FAZE[event.phase]
        log.info("%s: %d/%d gotovo", faza, event.done, event.total, extra={"domain": event.domain})


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
def _csv_tekst(path: Path) -> str:
    """Excel bez opcije „CSV UTF-8" na srpskom Windows-u čuva u windows-1250."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        log.warning("%s nije u UTF-8, čitam ga kao windows-1250", path)
        return raw.decode("cp1250", errors="replace")


def _razdvajac(zaglavlje: str) -> str:
    """Srpska podešavanja Windows-a: Excel kolone razdvaja sa `;`, ne sa zarezom."""
    return max(",;\t", key=zaglavlje.count) if any(c in zaglavlje for c in ",;\t") else ","


def _ceo_broj(najmanje: int):
    """Tip za argparse: ceo broj ≥ `najmanje`. Nula mesta u semaforu zaustavlja prolaz."""

    def parse(tekst: str) -> int:
        try:
            broj = int(tekst)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{tekst!r} nije ceo broj") from None
        if broj < najmanje:
            raise argparse.ArgumentTypeError(f"mora biti bar {najmanje}, a jeste {broj}")
        return broj

    return parse


def read_domains(path: Path, only: Sequence[str] = ()) -> list[DomainInput]:
    """CSV sa zaglavljem, ne gola lista domena (§4.1).

    Lista najčešće dolazi iz Excel-a, pa se prepoznaju i `;` i windows-1250. Isti
    domen dva puta znači dva prolaza kroz tuđ sajt — važi prvo pojavljivanje.
    """
    rows: list[DomainInput] = []
    viđeni: set[str] = set()
    tekst = _csv_tekst(path)
    zaglavlje = tekst.splitlines()[0] if tekst.strip() else ""
    reader = csv.DictReader(io.StringIO(tekst, newline=""), delimiter=_razdvajac(zaglavlje))
    if not reader.fieldnames or "domain" not in reader.fieldnames:
        raise SystemExit(f"{path}: nedostaje kolona `domain` u zaglavlju (§4.1)")
    for row in reader:
        domain = (row.get("domain") or "").strip()
        if not domain or domain.startswith("#"):
            continue
        if domain.lower() in viđeni:
            log.warning("domen se ponavlja u listi, preskačem ga", extra={"domain": domain})
            continue
        viđeni.add(domain.lower())
        industry = (row.get("industry") or "").strip().lower() or "ostalo"
        if industry not in INDUSTRIES:
            log.warning("nepoznata delatnost %r, koristim `ostalo`", industry, extra={"domain": domain})
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
    config = load_config(args.config)
    if args.concurrency:
        # Oba zajedno: više domena u radu nego slotova znači da budžet domena opet
        # teče dok čeka u redu.
        config["http"]["concurrency"] = args.concurrency
        config["http"]["domain_concurrency"] = args.concurrency
    if args.max_level2 is not None:
        config["escalation"]["max_level2"] = args.max_level2

    targets = read_domains(Path(args.domains), args.only)
    snapshots_dir = Path(args.snapshots or Path(args.out) / "snapshots")
    result = asyncio.run(
        pipeline.scan(targets, config, level=args.level, snapshot_dir=snapshots_dir, on_event=log_event)
    )
    _emit(result, config, args)
    return 0


def _emit(result: ScanResult, config: dict, args: argparse.Namespace) -> None:
    reports = result.ranked
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}

    if "csv" in formats:
        csv_out.write_findings(out / "findings.csv", reports, bom=args.csv_bom)
        csv_out.write_summary(out / "summary.csv", reports, bom=args.csv_bom)
    if "html" in formats:
        html_out.write(out / "index.html", reports, config, duration_s=result.duration_s["total"])

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
    _emit(pipeline.recheck(Path(args.snapshots), config, on_event=log_event), config, args)
    return 0


# --------------------------------------------------------------------------- #
# record — snima fixture-e (§12.2)
# --------------------------------------------------------------------------- #
def cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    targets = read_domains(Path(args.domains), args.only)
    out = Path(args.out)
    broj = asyncio.run(pipeline.record(targets, config, out_dir=out, level=args.level))
    print(f"snimljeno {broj} snapshota u {out}/", file=sys.stderr)
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
    scan.add_argument(
        "--concurrency", type=_ceo_broj(1), metavar="N", help="globalni semafor (podrazumevano 8)"
    )
    scan.add_argument("--max-level2", type=_ceo_broj(0), metavar="N", help="gornji limit za nivo 2 (60)")
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
    except InputError as exc:
        raise SystemExit(str(exc)) from exc
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
