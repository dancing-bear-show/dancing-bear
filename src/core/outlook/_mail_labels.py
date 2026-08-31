"""Labels (categories) and rules (filters) mixin for Outlook via Microsoft Graph."""

from __future__ import annotations

import time
from typing import Any, Protocol

from .client import OutlookClientBase, _requests
from core.constants import GRAPH_API_URL


class _LabelsHost(Protocol):
    """Complete self-type for LabelsFiltersMixin methods that call sibling methods.

    Declares what those methods need from OutlookClientBase/ConfigCacheMixin
    (cross-class requirements) plus LabelsFiltersMixin's own sibling methods
    that are called internally.
    """

    # --- From OutlookClientBase / ConfigCacheMixin ---
    def _headers(self) -> dict[str, str]: ...
    def cfg_get_json(self, name: str, ttl: int = ...) -> Any | None: ...
    def cfg_put_json(self, name: str, data: Any) -> None: ...

    # --- LabelsFiltersMixin's own sibling methods ---
    def list_labels(self, use_cache: bool = ..., ttl: int = ...) -> list[dict[str, Any]]: ...
    def create_label(self, name: str, color: dict[str, Any] | None = ..., **_kwargs: Any) -> dict[str, Any]: ...
    def get_label_id_map(self) -> dict[str, str]: ...
    def _fetch_inbox_rules_raw(self) -> list[dict[str, Any]]: ...
    def _map_rule(self, ru: dict[str, Any]) -> dict[str, Any]: ...
    def _build_rule_conditions(self, criteria: dict[str, Any]) -> dict[str, Any]: ...
    def _build_rule_actions(self, action: dict[str, Any]) -> dict[str, Any]: ...


class LabelsFiltersMixin:
    """Mixin providing label (category) and rule (filter) operations.

    Requires OutlookClientBase methods: _headers, cfg_get_json, cfg_put_json.
    """

    # -------------------- Categories (labels) --------------------
    def list_labels(
        self: OutlookClientBase,
        use_cache: bool = False,
        ttl: int = 300,
    ) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("categories", ttl)
            if isinstance(cached, list):
                cats = cached
            else:
                r = _requests().get(f"{GRAPH_API_URL}/me/outlook/masterCategories", headers=self._headers())
                r.raise_for_status()
                cats = r.json().get("value", [])
                self.cfg_put_json("categories", cats)
        else:
            r = _requests().get(f"{GRAPH_API_URL}/me/outlook/masterCategories", headers=self._headers())
            r.raise_for_status()
            cats = r.json().get("value", [])
        out = []
        for c in cats:
            entry = {
                "id": c.get("id"),
                "name": c.get("displayName"),
                "color": {"name": c.get("color")},
                "type": "user",
            }
            out.append(entry)
        return out

    def create_label(
        self: OutlookClientBase,
        name: str,
        color: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"displayName": name}
        if color and isinstance(color, dict) and color.get("name"):
            body["color"] = color.get("name")
        r = _requests().post(f"{GRAPH_API_URL}/me/outlook/masterCategories", headers=self._headers(), json=body)
        r.raise_for_status()
        c = r.json()
        return {"id": c.get("id"), "name": c.get("displayName")}

    def update_label(
        self: OutlookClientBase,
        label_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body.get("name"):
            payload["displayName"] = body["name"]
        if isinstance(body.get("color"), dict) and body["color"].get("name"):
            payload["color"] = body["color"]["name"]
        if not payload:
            return {}
        r = _requests().patch(
            f"{GRAPH_API_URL}/me/outlook/masterCategories/{label_id}",
            headers=self._headers(),
            json=payload,
        )
        r.raise_for_status()
        return r.json() if r.text else {}

    def delete_label(self: OutlookClientBase, label_id: str) -> None:
        r = _requests().delete(
            f"{GRAPH_API_URL}/me/outlook/masterCategories/{label_id}",
            headers=self._headers(),
        )
        r.raise_for_status()

    def get_label_id_map(self: "_LabelsHost") -> dict[str, str]:
        return {lbl.get("name", ""): lbl.get("id", "") for lbl in self.list_labels()}

    def ensure_label(self: "_LabelsHost", name: str, **kwargs: Any) -> str:
        m = self.get_label_id_map()
        if name in m:
            return m[name]
        created = self.create_label(name, **kwargs)
        return created.get("id", "")

    # -------------------- Rules (filters) --------------------
    def _fetch_inbox_rules_raw(self: OutlookClientBase) -> list[dict[str, Any]]:
        """Fetch raw inbox rules from Graph API."""
        r = _requests().get(
            f"{GRAPH_API_URL}/me/mailFolders/inbox/messageRules",
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json().get("value", [])

    def _map_rule(self: OutlookClientBase, ru: dict[str, Any]) -> dict[str, Any]:
        """Map a raw Graph rule to the internal filter format."""
        cond = ru.get("conditions", {}) or {}
        act = ru.get("actions", {}) or {}
        crit: dict[str, Any] = {}
        if cond.get("senderContains"):
            crit["from"] = " OR ".join(cond["senderContains"])
        if cond.get("recipientContains"):
            crit["to"] = " OR ".join(cond["recipientContains"])
        if cond.get("subjectContains"):
            crit["subject"] = " OR ".join(cond["subjectContains"])
        action: dict[str, Any] = {}
        if act.get("assignCategories"):
            action["addLabelIds"] = act["assignCategories"]
        if act.get("forwardTo"):
            action["forward"] = ",".join(
                a.get("emailAddress", {}).get("address", "") for a in act["forwardTo"]
            )
        if act.get("moveToFolder"):
            action["moveToFolderId"] = act.get("moveToFolder")
        return {"id": ru.get("id"), "criteria": crit, "action": action}

    def list_filters(
        self: "_LabelsHost",
        use_cache: bool = False,
        ttl: int = 300,
    ) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("rules_inbox", ttl)
            rules = cached if isinstance(cached, list) else self._fetch_inbox_rules_raw()
            if not isinstance(cached, list):
                self.cfg_put_json("rules_inbox", rules)
        else:
            rules = self._fetch_inbox_rules_raw()
        return [self._map_rule(ru) for ru in rules]

    def _build_rule_conditions(self: OutlookClientBase, criteria: dict[str, Any]) -> dict[str, Any]:
        """Convert filter criteria dict to Graph API conditions format."""
        cond: dict[str, Any] = {}
        if criteria.get("from"):
            cond["senderContains"] = [s.strip() for s in str(criteria["from"]).split("OR")]
        if criteria.get("to"):
            cond["recipientContains"] = [s.strip() for s in str(criteria["to"]).split("OR")]
        if criteria.get("subject"):
            cond["subjectContains"] = [s.strip() for s in str(criteria["subject"]).split("OR")]
        return cond

    def _build_rule_actions(self: OutlookClientBase, action: dict[str, Any]) -> dict[str, Any]:
        """Convert filter action dict to Graph API actions format."""
        act: dict[str, Any] = {}
        if action.get("addLabelIds"):
            act["assignCategories"] = action["addLabelIds"]
        if action.get("forward"):
            emails = [e.strip() for e in str(action["forward"]).split(",") if e.strip()]
            act["forwardTo"] = [{"emailAddress": {"address": e}} for e in emails]
        if action.get("moveToFolderId"):
            act["moveToFolder"] = action["moveToFolderId"]
        return act

    def create_filter(
        self: "_LabelsHost",
        criteria: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "displayName": f"Rule {int(time.time())}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": self._build_rule_conditions(criteria),
            "actions": self._build_rule_actions(action),
            "stopProcessingRules": True,
        }
        r = _requests().post(
            f"{GRAPH_API_URL}/me/mailFolders/inbox/messageRules",
            headers=self._headers(),
            json=payload,
        )
        r.raise_for_status()
        return r.json()

    def delete_filter(self: OutlookClientBase, filter_id: str) -> None:
        r = _requests().delete(
            f"{GRAPH_API_URL}/me/mailFolders/inbox/messageRules/{filter_id}",
            headers=self._headers(),
        )
        r.raise_for_status()
