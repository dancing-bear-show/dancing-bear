"""Metals Assistant CLI.

Precious metals portfolio tracking and analysis.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from core.cli_framework import CLIApp

from .. import APP_ID, PURPOSE

app = CLIApp(
    APP_ID,
    f"{PURPOSE}",
    epilog="Use --help on subcommands for details.",
)


# ============================================================================
# Extract Commands
# ============================================================================

extract_group = app.group("extract", help="Extract metals data from emails")


@extract_group.command("gmail", help="Extract from Gmail")
@app.argument("--profile", "-p", default="gmail_personal", help="Gmail profile")
@app.argument("--days", "-d", type=int, default=365, help="Days to search")
def cmd_extract_gmail(args) -> int:
    from ..pipeline import ExtractRequest, GmailExtractProcessor, ExtractProducer

    request = ExtractRequest(
        profile=args.profile,
        days=args.days,
        provider="gmail",
    )
    processor = GmailExtractProcessor()
    producer = ExtractProducer()

    result = processor.process(request)
    producer.produce(result)
    return 0 if result.ok() else 1


@extract_group.command("outlook", help="Extract from Outlook")
@app.argument("--profile", "-p", default="outlook_personal", help="Outlook profile")
@app.argument("--days", "-d", type=int, default=365, help="Days to search")
def cmd_extract_outlook(args) -> int:
    from ..pipeline import ExtractRequest, OutlookExtractProcessor, ExtractProducer

    request = ExtractRequest(
        profile=args.profile,
        days=args.days,
        provider="outlook",
    )
    processor = OutlookExtractProcessor()
    producer = ExtractProducer()

    result = processor.process(request)
    producer.produce(result)
    return 0 if result.ok() else 1


# ============================================================================
# Costs Commands
# ============================================================================

costs_group = app.group("costs", help="Extract and manage purchase costs")


@costs_group.command("gmail", help="Extract costs from Gmail")
@app.argument("--profile", "-p", default="gmail_personal", help="Gmail profile")
@app.argument("--out", "-o", default="out/metals/costs.csv", help="Output CSV path")
def cmd_costs_gmail(args) -> int:
    from .costs import main as costs_main
    return costs_main(["--profile", args.profile, "--out", args.out])


@costs_group.command("outlook", help="Extract costs from Outlook (RCM)")
@app.argument("--profile", "-p", default="outlook_personal", help="Outlook profile")
@app.argument("--out", "-o", default="out/metals/costs.csv", help="Output CSV path")
def cmd_costs_outlook(args) -> int:
    from .outlook_costs import main as outlook_costs_main
    return outlook_costs_main(["--profile", args.profile, "--out", args.out])


# ============================================================================
# Spot Commands
# ============================================================================

spot_group = app.group("spot", help="Fetch and manage spot prices")


@spot_group.command("fetch", help="Fetch daily spot prices")
@app.argument("--metal", "-m", choices=["gold", "silver"], default="gold", help="Metal type")
@app.argument("--start", "-s", help="Start date (YYYY-MM-DD)")
@app.argument("--out-dir", "-o", default="out/metals", help="Output directory")
def cmd_spot_fetch(args) -> int:
    from .spot import main as spot_main
    argv = ["--metal", args.metal, "--out-dir", args.out_dir]
    if args.start:
        argv.extend(["--start", args.start])
    return spot_main(argv)


# ============================================================================
# Premium Commands
# ============================================================================

premium_group = app.group("premium", help="Calculate purchase premiums")


@premium_group.command("calc", help="Calculate premium over spot")
@app.argument("--metal", "-m", choices=["gold", "silver"], help="Metal type (default: both)")
@app.argument("--costs", default="out/metals/costs.csv", help="Costs CSV path")
@app.argument("--spot-dir", default="out/metals", help="Spot prices directory")
def cmd_premium_calc(args) -> int:
    from .premium import main as premium_main
    argv = ["--costs", args.costs, "--spot-dir", args.spot_dir]
    if args.metal:
        argv.extend(["--metal", args.metal])
    return premium_main(argv)


@premium_group.command("summary", help="Summarize premiums")
@app.argument("--out-dir", "-o", default="out/metals", help="Output directory")
def cmd_premium_summary(args) -> int:
    from .premium_summary import main as summary_main
    return summary_main(["--out-dir", args.out_dir])


# ============================================================================
# Build Commands
# ============================================================================

build_group = app.group("build", help="Build summary files")


@build_group.command("summaries", help="Build gold/silver summary CSVs")
@app.argument("--costs", default="out/metals/costs.csv", help="Costs CSV path")
@app.argument("--out-dir", "-o", default="out/metals", help="Output directory")
def cmd_build_summaries(args) -> int:
    from .build_summaries import main as build_main
    return build_main(["--costs", args.costs, "--out-dir", args.out_dir])


# ============================================================================
# Excel Commands
# ============================================================================

excel_group = app.group("excel", help="Excel/OneDrive integration")


@excel_group.command("merge", help="Merge summaries into Excel workbook")
@app.argument("--workbook", "-w", required=True, help="Source workbook path")
@app.argument("--out", "-o", help="Output workbook path")
@app.argument("--gold", default="out/metals/gold_summary.csv", help="Gold summary CSV")
@app.argument("--silver", default="out/metals/silver_summary.csv", help="Silver summary CSV")
def cmd_excel_merge(args) -> int:
    from .excel_merge import main as merge_main
    argv = ["--workbook", args.workbook, "--gold", args.gold, "--silver", args.silver]
    if args.out:
        argv.extend(["--out", args.out])
    return merge_main(argv)


# ============================================================================
# Scan Commands
# ============================================================================

@app.command("scan", help="Scan for metals emails (Outlook)")
@app.argument("--profile", "-p", default="outlook_personal", help="Outlook profile")
def cmd_scan(args) -> int:
    from .outlook_scan import main as scan_main
    return scan_main(["--profile", args.profile])


# ============================================================================
# Main
# ============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    return app.run(argv)


if __name__ == "__main__":
    sys.exit(main())
