"""Pipeline pattern for metals extraction workflows.

Uses the core pipeline pattern with processors and producers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.cli_errors import CLIError
from core.pipeline import RequestConsumer, SafeProcessor, BaseProducer

from .extractors import MetalsAmount, OrderExtraction


DEFAULT_COSTS_PATH = "out/metals/costs.csv"


# ============================================================================
# Request/Result Types
# ============================================================================

@dataclass
class ExtractRequest:
    """Request to extract metals from emails."""
    profile: str = "gmail_personal"
    days: int = 365
    provider: str = "gmail"  # gmail or outlook


@dataclass
class ExtractResult:
    """Result of metals extraction."""
    total: MetalsAmount
    orders: list[OrderExtraction] = field(default_factory=list)
    message_count: int = 0


@dataclass
class SpotPriceRequest:
    """Request to fetch spot prices."""
    metal: str  # gold or silver
    start_date: str | None = None  # YYYY-MM-DD; None = auto-detect
    end_date: str | None = None
    out_path: str = ""  # output CSV path; empty = default per metal


@dataclass
class SpotPrice:
    """Daily spot price."""
    date: str
    price_usd: float
    price_cad: float


@dataclass
class SpotPriceResult:
    """Result of spot price fetch."""
    metal: str
    out_path: str = ""
    row_count: int = 0
    window: str = ""
    prices: list[SpotPrice] = field(default_factory=list)


@dataclass
class PremiumRequest:
    """Request to calculate purchase premiums."""
    costs_path: str = DEFAULT_COSTS_PATH
    spot_dir: str = "out/metals"


@dataclass
class PremiumResult:
    """Result of premium calculation."""
    metal: str
    avg_premium_pct: float
    orders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GmailCostsRequest:
    """Request to extract costs from Gmail order emails."""
    profile: str = "gmail_personal"
    out_path: str = DEFAULT_COSTS_PATH


@dataclass
class GmailCostsResult:
    """Result of Gmail costs extraction."""
    out_path: str
    row_count: int


@dataclass
class OutlookCostsRequest:
    """Request to extract costs from Outlook order emails."""
    profile: str = "outlook_personal"
    out_path: str = DEFAULT_COSTS_PATH


@dataclass
class OutlookCostsResult:
    """Result of Outlook costs extraction."""
    out_path: str
    row_count: int


# ============================================================================
# Consumers (type aliases using generic RequestConsumer)
# ============================================================================

ExtractRequestConsumer = RequestConsumer[ExtractRequest]
SpotPriceRequestConsumer = RequestConsumer[SpotPriceRequest]
PremiumRequestConsumer = RequestConsumer[PremiumRequest]
GmailCostsRequestConsumer = RequestConsumer[GmailCostsRequest]
OutlookCostsRequestConsumer = RequestConsumer[OutlookCostsRequest]


# ============================================================================
# Processors
# ============================================================================

class GmailExtractProcessor(SafeProcessor[ExtractRequest, ExtractResult]):
    """Extracts metals data from Gmail."""

    def _process_safe(self, request: ExtractRequest) -> ExtractResult:
        from mail.config_resolver import resolve_paths_profile
        from mail.gmail_api import GmailClient
        from .extractors import extract_amounts, extract_order_id, MetalsAmount

        cred, tok = resolve_paths_profile(
            arg_credentials=None,
            arg_token=None,
            profile=request.profile,
        )
        client = GmailClient(
            credentials_path=cred,
            token_path=tok,
            cache_dir=".cache",
        )
        client.authenticate()

        queries = [
            'from:noreply@td.com subject:"TD Precious Metals"',
            'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
            'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
            '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
        ]

        # Gather message IDs
        cand_ids: list[str] = []
        for q in queries:
            cand_ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
        cand_ids = list(dict.fromkeys(cand_ids))

        # Deduplicate by order ID, keeping latest message
        order_map: dict[str, tuple] = {}
        for mid in cand_ids:
            msg = client.get_message(mid, fmt="full")
            hdrs = GmailClient.headers_to_dict(msg)
            sub = hdrs.get("subject", "")
            text = client.get_message_text(mid)
            oid = extract_order_id(sub, text) or mid
            recv_ms = int(msg.get("internalDate") or 0)
            cur = order_map.get(oid)
            if not cur or recv_ms > cur[1]:
                order_map[oid] = (mid, recv_ms, sub)

        # Extract amounts
        total = MetalsAmount()
        orders: list[OrderExtraction] = []
        for oid, (mid, recv_ms, sub) in order_map.items():
            text = client.get_message_text(mid)
            amounts = extract_amounts(text)
            total = total + amounts
            if amounts.has_metals():
                orders.append(OrderExtraction(
                    order_id=oid,
                    message_id=mid,
                    gold_oz=amounts.gold_oz,
                    silver_oz=amounts.silver_oz,
                    subject=sub,
                    date_ms=recv_ms,
                ))

        return ExtractResult(
            total=total,
            orders=orders,
            message_count=len(order_map),
        )


class OutlookExtractProcessor(SafeProcessor[ExtractRequest, ExtractResult]):
    """Extracts metals data from Outlook."""

    def _process_safe(self, request: ExtractRequest) -> ExtractResult:
        from core.auth import resolve_outlook_credentials
        from mail.outlook_api import OutlookClient
        from .extractors import extract_amounts, extract_order_id, MetalsAmount

        client_id, tenant, token_path = resolve_outlook_credentials(
            request.profile, None, None, None
        )
        if not all([client_id, tenant, token_path]):
            raise CLIError("Missing Outlook credentials")

        client = OutlookClient(
            client_id=client_id,
            tenant=tenant,
            token_path=token_path,
        )

        # Search for metals emails
        kql = "(TD Precious Metals) OR (Costco order) OR (Royal Canadian Mint)"
        messages = client.search_messages(kql, top=200)

        # Deduplicate and extract
        order_map: dict[str, tuple] = {}
        for msg in messages:
            sub = msg.get("subject", "")
            body = msg.get("body", {}).get("content", "")
            oid = extract_order_id(sub, body) or msg.get("id", "")
            recv = msg.get("receivedDateTime", "")
            cur = order_map.get(oid)
            if not cur or recv > cur[1]:
                order_map[oid] = (msg.get("id"), recv, sub, body)

        total = MetalsAmount()
        orders: list[OrderExtraction] = []
        for oid, (mid, recv, sub, body) in order_map.items():
            amounts = extract_amounts(body)
            total = total + amounts
            if amounts.has_metals():
                orders.append(OrderExtraction(
                    order_id=oid,
                    message_id=mid,
                    gold_oz=amounts.gold_oz,
                    silver_oz=amounts.silver_oz,
                    subject=sub,
                ))

        return ExtractResult(
            total=total,
            orders=orders,
            message_count=len(order_map),
        )


# ============================================================================
# Spot Price Processor / Producer (C2, C6, C10)
# ============================================================================

class SpotPriceProcessor(SafeProcessor[SpotPriceRequest, SpotPriceResult]):
    """Fetches daily spot prices and writes to CSV.

    Wraps the bare spot.run() function path in a SafeProcessor contract.
    SpotPriceRequest is wired here (pipeline.py:36); no duplication needed.
    """

    def _process_safe(self, request: SpotPriceRequest) -> SpotPriceResult:
        import csv as _csv
        from datetime import date as _date, timedelta as _td
        from pathlib import Path
        from .spot import (
            _auto_start_date,
            _today_iso,
            _fetch_series_with_fallback,
            _build_csv_rows,
        )

        metal = (request.metal or "").strip().lower()
        out_path = request.out_path or f"out/metals/{metal}_spot_cad_daily.csv"
        sdate = request.start_date or _auto_start_date(metal) or (
            _date.today() - _td(days=365)
        ).isoformat()
        edate = request.end_date or _today_iso()

        usd, fx = _fetch_series_with_fallback(metal, sdate, edate)
        rows = _build_csv_rows(metal, usd, fx, sdate, edate)

        op = Path(out_path)
        op.parent.mkdir(parents=True, exist_ok=True)
        with op.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerows(rows)

        return SpotPriceResult(
            metal=metal,
            out_path=out_path,
            row_count=len(rows) - 1,  # exclude header
            window=f"{sdate}..{edate}",
        )


class SpotPriceProducer(BaseProducer):
    """Produces output from spot price fetch results."""

    def _produce_success(self, payload: SpotPriceResult, diagnostics: Optional[dict[str, Any]]) -> None:
        self._writer.print(
            f"wrote {payload.out_path} rows={payload.row_count} window={payload.window}"
        )


# ============================================================================
# Gmail Costs Processor / Producer (C2, C6)
# ============================================================================

class GmailCostsProcessor(SafeProcessor[GmailCostsRequest, GmailCostsResult]):
    """Extracts per-order costs from Gmail and writes to CSV.

    Wraps the GmailCostExtractor bare-function path in a SafeProcessor contract.
    """

    def _process_safe(self, request: GmailCostsRequest) -> GmailCostsResult:
        from .gmail_costs_extract import GmailCostExtractor
        extractor = GmailCostExtractor(
            profile=request.profile,
            out_path=request.out_path,
            days=365,
        )
        extractor.run()
        return GmailCostsResult(out_path=request.out_path, row_count=extractor.last_row_count)


class GmailCostsProducer(BaseProducer):
    """Produces output from Gmail costs extraction results."""

    def _produce_success(self, payload: GmailCostsResult, diagnostics: Optional[dict[str, Any]]) -> None:
        self._writer.print(f"wrote {payload.out_path} rows={payload.row_count}")


# ============================================================================
# Outlook Costs Processor / Producer (C2, C6)
# ============================================================================

class OutlookCostsProcessor(SafeProcessor[OutlookCostsRequest, OutlookCostsResult]):
    """Extracts per-order costs from Outlook and writes to CSV.

    Wraps the outlook_costs.run() bare-function path in a SafeProcessor contract.
    """

    def _process_safe(self, request: OutlookCostsRequest) -> OutlookCostsResult:
        from .outlook_costs import run as _costs_run
        _costs_run(profile=request.profile, out_path=request.out_path)
        # NOTE: outlook_costs.run() (the module-level wrapper, patched by
        # tests/metals_tests/pipeline/test_new_processors.py) does not expose
        # the underlying OutlookCostExtractor instance, so the real row count
        # is not available here. Calling OutlookCostExtractor directly would
        # bypass the wrapper's test seam and execute a live network call in
        # tests that patch metals.outlook_costs.run. Row count is left at the
        # dataclass default (0) on this path; see GmailCostsProcessor for the
        # equivalent Gmail path, where the extractor IS constructed directly
        # and last_row_count is available.
        return OutlookCostsResult(out_path=request.out_path, row_count=0)


class OutlookCostsProducer(BaseProducer):
    """Produces output from Outlook costs extraction results."""

    def _produce_success(self, payload: OutlookCostsResult, diagnostics: Optional[dict[str, Any]]) -> None:
        self._writer.print(f"wrote {payload.out_path} rows={payload.row_count}")


# ============================================================================
# Producers
# ============================================================================

class ExtractProducer(BaseProducer):
    """Produces output from extraction results."""

    def _produce_success(self, payload: ExtractResult, diagnostics: Optional[dict[str, Any]]) -> None:
        total = payload.total
        self._writer.print(f"gold_oz={total.gold_oz:.3f} silver_oz={total.silver_oz:.3f}")
        self._writer.print(
            f"Processed {payload.message_count} messages, found {len(payload.orders)} orders with metals"
        )

        if payload.orders:
            self._writer.print("\nSample orders:")
            for order in payload.orders[:10]:
                self._writer.print(
                    f"  - {order.order_id}: gold={order.gold_oz:.3f} silver={order.silver_oz:.3f}"
                )
