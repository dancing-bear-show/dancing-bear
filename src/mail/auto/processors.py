"""Processors for auto pipelines."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor

from .consumers import AutoProposePayload, AutoSummaryPayload, AutoApplyPayload
from ..utils.senders import is_protected_sender


_PROMO_KEYWORDS = ["sale", "% off", "percent off", "deal", "promo", "clearance", "free shipping", "coupon"]


def _detect_low_interest_reasons(hdrs: dict, label_ids: set, subject: str) -> list[str]:
    """Return list of low-interest reason tags for a message."""
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
    if any(k in subject for k in _PROMO_KEYWORDS):
        reasons.append("promo-subject")
    return reasons


def classify_low_interest(msg: dict) -> dict | None:
    """Return action suggestion if message is likely low-interest.

    Heuristics: list-Unsubscribe/list-Id headers, Precedence: bulk, Auto-Submitted,
    Gmail categories (CATEGORY_PROMOTIONS/FORUMS), promo keywords in subject.
    """
    from ..gmail_api import GmailClient

    hdrs = GmailClient.headers_to_dict(msg)
    label_ids = set(msg.get("labelIds", []) or [])
    subject = (hdrs.get("subject") or "").lower()
    from_addr = hdrs.get("from") or ""

    reasons = _detect_low_interest_reasons(hdrs, label_ids, subject)
    if not reasons:
        return None

    # Choose target label
    if "category:promotions" in reasons or "promo-subject" in reasons:
        add = ["Lists/Commercial"]
    else:
        add = ["Lists/Newsletters"]

    return {
        "add": add,
        "remove": ["INBOX"],
        "reasons": reasons,
        "from": from_addr,
        "subject": hdrs.get("subject") or "",
        "ts": int(msg.get("internalDate", 0)),
    }


@dataclass
class AutoProposeResult:
    """Result of auto propose."""

    out_path: Path | None = None
    total_considered: int = 0
    selected_count: int = 0
    query: str = ""


@dataclass
class AutoSummaryResult:
    """Result of auto summary."""

    message_count: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    label_adds: dict[str, int] = field(default_factory=dict)


@dataclass
class AutoApplyResult:
    """Result of auto apply."""

    total_modified: int = 0
    dry_run: bool = False
    groups: list[tuple[int, list[str], list[str]]] = field(default_factory=list)  # (count, add_ids, rem_ids)


class AutoProposeProcessor(SafeProcessor[AutoProposePayload, AutoProposeResult]):
    """Create proposal for categorizing + archiving low-interest mail."""

    def _process_safe(self, payload: AutoProposePayload) -> AutoProposeResult:
        from ..applog import AppLogger
        from ..gmail_api import GmailClient
        from ..utils.gmail_ops import MessageQueryParams, fetch_messages_with_metadata

        logger = AppLogger(payload.log_path)
        sid = logger.start("auto_propose", {"days": payload.days, "pages": payload.pages})
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()

            # Build query for inbox messages within days
            q = f"in:inbox newer_than:{payload.days}d"
            _, msgs = fetch_messages_with_metadata(
                client,
                MessageQueryParams(query=q, pages=payload.pages),
            )

            selected = []
            prot = [p.strip().lower() for p in payload.protect if p and isinstance(p, str)]

            for m in msgs:
                hdrs = GmailClient.headers_to_dict(m)
                if is_protected_sender(hdrs.get("from", ""), prot):
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

            from core.fileutil import atomic_write_json
            atomic_write_json(payload.out_path, doc)

            logger.end(sid, status="ok")
            return AutoProposeResult(
                out_path=payload.out_path,
                total_considered=len(msgs),
                selected_count=len(selected),
                query=q,
            )
        except Exception as e:
            logger.error(sid, f"auto_propose failed: {e}")
            logger.end(sid, status="error", error=str(e))
            raise


class AutoSummaryProcessor(SafeProcessor[AutoSummaryPayload, AutoSummaryResult]):
    """Summarize a proposal."""

    def _process_safe(self, payload: AutoSummaryPayload) -> AutoSummaryResult:
        msgs = payload.proposal.get("messages") or []
        reasons: Counter = Counter()
        add_labels: Counter = Counter()

        for m in msgs:
            for r in m.get("reasons") or []:
                reasons[r] += 1
            for a in m.get("add") or []:
                add_labels[a] += 1

        return AutoSummaryResult(
            message_count=len(msgs),
            reasons=dict(reasons.most_common(10)),
            label_adds=dict(add_labels.most_common()),
        )


def _group_messages_by_labels(
    msgs: list, name_to_id: dict, cutoff_ts: int | None
) -> dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]]:
    """Group message IDs by their (add_ids, remove_ids) label signature."""
    groups: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = defaultdict(list)
    for m in msgs:
        if cutoff_ts and int(m.get("ts", 0)) > cutoff_ts:
            continue
        add_ids = tuple(sorted(name_to_id.get(x) or x for x in (m.get("add") or [])))
        rem_ids = tuple(sorted(name_to_id.get(x) or x for x in (m.get("remove") or [])))
        groups[(add_ids, rem_ids)].append(m.get("id"))
    return groups


class AutoApplyProcessor(SafeProcessor[AutoApplyPayload, AutoApplyResult]):
    """Apply a proposal to modify messages."""

    def _process_safe(self, payload: AutoApplyPayload) -> AutoApplyResult:
        from ..applog import AppLogger

        logger = AppLogger(payload.log_path)
        sid = logger.start("auto_apply", {"dry_run": payload.dry_run, "batch_size": payload.batch_size})
        try:
            msgs = payload.proposal.get("messages") or []
            client = payload.context.get_gmail_client()
            client.authenticate()
            name_to_id = client.get_label_id_map()

            cutoff_ts = None
            if payload.cutoff_days:
                cutoff_ts = int(time.time()) - payload.cutoff_days * 86400

            groups = _group_messages_by_labels(msgs, name_to_id, cutoff_ts)
            total, result_groups = self._apply_groups(client, groups, payload)

            logger.end(sid, status="ok")
            return AutoApplyResult(
                total_modified=total,
                dry_run=payload.dry_run,
                groups=result_groups,
            )
        except Exception as e:
            logger.error(sid, f"auto_apply failed: {e}")
            logger.end(sid, status="error", error=str(e))
            raise

    def _apply_groups(
        self,
        client: Any,
        groups: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]],
        payload: AutoApplyPayload,
    ) -> tuple[int, list[tuple[int, list[str], list[str]]]]:
        """Apply label changes per group; return (total, result_groups)."""
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
        return total, result_groups
