"""Processors for auto pipelines."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.pipeline import Processor, ResultEnvelope

from .consumers import AutoProposePayload, AutoSummaryPayload, AutoApplyPayload


def classify_low_interest(msg: dict) -> Optional[dict]:
    """Return action suggestion if message is likely low-interest.

    Heuristics: List-Unsubscribe/List-Id headers, Precedence: bulk, Auto-Submitted,
    Gmail categories (CATEGORY_PROMOTIONS/FORUMS), promo keywords in subject.
    """
    from ..gmail_api import GmailClient

    hdrs = GmailClient.headers_to_dict(msg)
    label_ids = set(msg.get("labelIds", []) or [])
    subject = (hdrs.get("subject") or "").lower()
    from_addr = hdrs.get("from") or ""
    reasons = []

    if hdrs.get("list-unsubscribe") or hdrs.get("list-id"):
        reasons.append("list")
    if (hdrs.get("precedence") or "").lower() in {"bulk", "list"}:
        reasons.append("bulk")
    if (hdrs.get("auto-submitted") or "").lower() not in {"", "no"}:
        reasons.append("auto-submitted")
    if "category_promotions" in label_ids or "CATEGORY_PROMOTIONS" in label_ids:
        reasons.append("category:promotions")
    if "CATEGORY_FORUMS" in label_ids:
        reasons.append("category:forums")

    promo_kw = ["sale", "% off", "percent off", "deal", "promo", "clearance", "free shipping", "coupon"]
    if any(k in subject for k in promo_kw):
        reasons.append("promo-subject")

    if not reasons:
        return None

    # Choose target label
    add = []
    if "category:promotions" in reasons or "promo-subject" in reasons:
        add.append("Lists/Commercial")
    else:
        add.append("Lists/Newsletters")

    return {
        "add": add,
        "remove": ["INBOX"],
        "reasons": reasons,
        "from": from_addr,
        "subject": hdrs.get("subject") or "",
        "ts": int(msg.get("internalDate", 0)),
    }


def _is_protected(from_val: str, protected_patterns: List[str]) -> bool:
    """Check if sender matches any protected pattern."""
    f = (from_val or "").lower()
    # Extract bare email if in Name <email>
    if "<" in f and ">" in f:
        try:
            f = f.split("<")[-1].split(">")[0]
        except Exception:  # nosec B110 - malformed From header, fall back to original
            pass
    f = f.strip()
    dom = f.split("@")[-1] if "@" in f else f

    for p in protected_patterns:
        if not p:
            continue
        if p.startswith("@"):
            if f.endswith(p) or dom == p.lstrip("@"):
                return True
        elif p in (f,):
            return True
    return False


@dataclass
class AutoProposeResult:
    """Result of auto propose."""

    out_path: Optional[Path] = None
    total_considered: int = 0
    selected_count: int = 0
    query: str = ""


@dataclass
class AutoSummaryResult:
    """Result of auto summary."""

    message_count: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)
    label_adds: Dict[str, int] = field(default_factory=dict)


@dataclass
class AutoApplyResult:
    """Result of auto apply."""

    total_modified: int = 0
    dry_run: bool = False
    groups: List[Tuple[int, List[str], List[str]]] = field(default_factory=list)  # (count, add_ids, rem_ids)


class AutoProposeProcessor(Processor[AutoProposePayload, ResultEnvelope[AutoProposeResult]]):
    """Create proposal for categorizing + archiving low-interest mail."""

    def process(self, payload: AutoProposePayload) -> ResultEnvelope[AutoProposeResult]:
        try:
            from ..applog import AppLogger
            from ..utils.gmail_ops import fetch_messages_with_metadata
            from ..gmail_api import GmailClient

            logger = AppLogger(payload.log_path)
            sid = logger.start("auto_propose", {"days": payload.days, "pages": payload.pages})

            try:
                client = payload.context.get_gmail_client()
                client.authenticate()

                # Build query for inbox messages within days
                q = f"in:inbox newer_than:{payload.days}d"
                ids, msgs = fetch_messages_with_metadata(
                    client,
                    query=q,
                    pages=payload.pages,
                    max_msgs=None,
                )

                selected = []
                prot = [p.strip().lower() for p in payload.protect if p and isinstance(p, str)]

                for m in msgs:
                    hdrs = GmailClient.headers_to_dict(m)
                    if _is_protected(hdrs.get("from", ""), prot):
                        continue
                    act = classify_low_interest(m)
                    if act:
                        selected.append(
                            {
                                "id": m.get("id"),
                                "threadId": m.get("threadId"),
                                **act,
                            }
                        )

                doc = {
                    "generated_at": int(time.time()),
                    "days": payload.days,
                    "query": q,
                    "counts": {"total_considered": len(msgs), "selected": len(selected)},
                    "messages": selected,
                }

                import json

                payload.out_path.parent.mkdir(parents=True, exist_ok=True)
                payload.out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

                logger.end(sid, status="ok")
                return ResultEnvelope(
                    status="success",
                    payload=AutoProposeResult(
                        out_path=payload.out_path,
                        total_considered=len(msgs),
                        selected_count=len(selected),
                        query=q,
                    ),
                )
            except Exception as e:
                logger.error(sid, f"auto_propose failed: {e}")
                logger.end(sid, status="error", error=str(e))
                raise
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class AutoSummaryProcessor(Processor[AutoSummaryPayload, ResultEnvelope[AutoSummaryResult]]):
    """Summarize a proposal."""

    def process(self, payload: AutoSummaryPayload) -> ResultEnvelope[AutoSummaryResult]:
        try:
            msgs = payload.proposal.get("messages") or []
            reasons: Counter = Counter()
            add_labels: Counter = Counter()

            for m in msgs:
                for r in m.get("reasons") or []:
                    reasons[r] += 1
                for a in m.get("add") or []:
                    add_labels[a] += 1

            return ResultEnvelope(
                status="success",
                payload=AutoSummaryResult(
                    message_count=len(msgs),
                    reasons=dict(reasons.most_common(10)),
                    label_adds=dict(add_labels.most_common()),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class AutoApplyProcessor(Processor[AutoApplyPayload, ResultEnvelope[AutoApplyResult]]):
    """Apply a proposal to modify messages."""

    def process(self, payload: AutoApplyPayload) -> ResultEnvelope[AutoApplyResult]:
        try:
            from ..applog import AppLogger

            logger = AppLogger(payload.log_path)
            sid = logger.start("auto_apply", {"dry_run": payload.dry_run, "batch_size": payload.batch_size})

            try:
                msgs = payload.proposal.get("messages") or []
                client = payload.context.get_gmail_client()
                client.authenticate()
                name_to_id = client.get_label_id_map()

                groups: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], List[str]] = defaultdict(list)
                cutoff_ts = None
                if payload.cutoff_days:
                    cutoff_ts = int(time.time()) - payload.cutoff_days * 86400

                for m in msgs:
                    if cutoff_ts and int(m.get("ts", 0)) > cutoff_ts:
                        continue
                    add_ids = tuple(sorted(name_to_id.get(x) or x for x in (m.get("add") or [])))
                    rem_ids = tuple(sorted(name_to_id.get(x) or x for x in (m.get("remove") or [])))
                    sig = (add_ids, rem_ids)
                    groups[sig].append(m.get("id"))

                total = 0
                result_groups = []
                B = payload.batch_size

                for (add_ids, rem_ids), id_list in groups.items():
                    result_groups.append((len(id_list), list(add_ids), list(rem_ids)))
                    if payload.dry_run:
                        total += len(id_list)
                        continue
                    for i in range(0, len(id_list), B):
                        client.batch_modify_messages(id_list[i : i + B], list(add_ids), list(rem_ids))
                    total += len(id_list)

                logger.end(sid, status="ok")
                return ResultEnvelope(
                    status="success",
                    payload=AutoApplyResult(
                        total_modified=total,
                        dry_run=payload.dry_run,
                        groups=result_groups,
                    ),
                )
            except Exception as e:
                logger.error(sid, f"auto_apply failed: {e}")
                logger.end(sid, status="error", error=str(e))
                raise
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )
