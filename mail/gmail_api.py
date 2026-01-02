"""Minimal Gmail API wrapper (cleaned).

Provides the subset needed by the CLI with lazy imports of Google libs.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    # Imported here; CLI avoids importing this module on --help unless used.
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Request = Credentials = InstalledAppFlow = build = None  # type: ignore

from core.cache import ConfigCacheMixin
from core.text_utils import html_to_text
from .cache import MailCache

SCOPES = [
    # Settings and labels (labels, filters, sendAs/signatures, forwarding settings)
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
    # Read/search
    "https://www.googleapis.com/auth/gmail.readonly",
    # Modify labels and batch modify
    "https://www.googleapis.com/auth/gmail.modify",
    # Drafts (create/read/update/delete) and send messages
    "https://www.googleapis.com/auth/gmail.compose",
    # Send-only (explicitly allow direct send)
    "https://www.googleapis.com/auth/gmail.send",
]


def ensure_google_api() -> None:
    """Ensure optional Google API dependencies are present."""
    if Credentials is None or InstalledAppFlow is None or build is None or Request is None:
        raise RuntimeError(
            "Google API libraries not installed. Please `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`."
        )


class GmailClient(ConfigCacheMixin):
    def __init__(self, credentials_path: str, token_path: str, cache_dir: Optional[str] = None) -> None:
        ConfigCacheMixin.__init__(self, cache_dir, provider="gmail")
        self.credentials_path = os.path.expanduser(credentials_path)
        self.token_path = os.path.expanduser(token_path)
        self.creds: Optional[Credentials] = None  # type: ignore
        self._service = None
        self.cache = MailCache(cache_dir) if cache_dir else None
        self.cache_dir = cache_dir

    def authenticate(self) -> None:
        ensure_google_api()

        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception:
                creds = None

        if creds and creds.expired and getattr(creds, "refresh_token", None):
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if creds is None:
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            token_dir = os.path.dirname(self.token_path)
            if token_dir:
                os.makedirs(token_dir, exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        self.creds = creds
        self._service = build("gmail", "v1", credentials=self.creds)

    @property
    def service(self):
        if not self._service:
            raise RuntimeError("GmailClient not authenticated. Call authenticate().")
        return self._service

    def get_profile(self) -> Dict[str, Any]:
        return self.service.users().getProfile(userId="me").execute()

    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("labels", ttl)
            if isinstance(cached, list):
                return cached
        resp = self.service.users().labels().list(userId="me").execute()
        labs = resp.get("labels", [])
        if use_cache:
            self.cfg_put_json("labels", labs)
        return labs

    def get_label_id_map(self) -> Dict[str, str]:
        return {lab.get("name", ""): lab.get("id", "") for lab in self.list_labels()}

    # --- Label helpers ---
    def create_label(
        self,
        name: str,
        color: Optional[Dict[str, str]] = None,
        labelListVisibility: Optional[str] = None,
        messageListVisibility: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": name}
        if color:
            body["color"] = color
        if labelListVisibility:
            body["labelListVisibility"] = labelListVisibility
        if messageListVisibility:
            body["messageListVisibility"] = messageListVisibility
        # Allow caller to pass a prebuilt body via kwargs
        for k, v in kwargs.items():
            if k not in body:
                body[k] = v
        return self.service.users().labels().create(userId="me", body=body).execute()

    def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.service.users().labels().update(userId="me", id=label_id, body=body).execute()

    def ensure_label(self, name: str, **kwargs: Any) -> str:
        """Ensure label exists; create if missing, return ID."""
        name_to_id = self.get_label_id_map()
        if name in name_to_id:
            return name_to_id[name]
        created = self.create_label(name=name, **kwargs)
        return created.get("id", "")

    # --- Signatures (sendAs) ---
    def list_send_as(self) -> List[Dict[str, Any]]:
        resp = self.service.users().settings().sendAs().list(userId="me").execute()
        return resp.get("sendAs", [])

    def list_signatures(self) -> List[Dict[str, Any]]:
        out = []
        for sa in self.list_send_as():
            out.append({
                "sendAsEmail": sa.get("sendAsEmail"),
                "isPrimary": sa.get("isPrimary", False),
                "signature": sa.get("signature", ""),
                "displayName": sa.get("displayName"),
            })
        return out

    def update_signature(self, send_as_email: str, signature_html: str) -> Dict[str, Any]:
        body = {"signature": signature_html}
        return self.service.users().settings().sendAs().patch(userId="me", sendAsEmail=send_as_email, body=body).execute()

    # --- Messages helpers for sweeping/merging ---
    def list_message_ids(
        self,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> List[str]:
        """List message IDs matching query/labels with efficient pagination."""
        from .paging import paginate_gmail_messages, gather_pages

        pages = paginate_gmail_messages(
            self.service.users().messages(), query=query, label_ids=label_ids, page_size=page_size
        )
        return gather_pages(pages, max_pages=max_pages)

    def batch_modify_messages(
        self,
        ids: List[str],
        add_label_ids: Optional[List[str]] = None,
        remove_label_ids: Optional[List[str]] = None,
    ) -> None:
        if not ids:
            return
        body: Dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        self.service.users().messages().batchModify(userId="me", body={"ids": ids, **body}).execute()

    def delete_label(self, label_id: str) -> None:
        self.service.users().labels().delete(userId="me", id=label_id).execute()

    # --- Filters and forwarding ---
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("filters", ttl)
            if isinstance(cached, list):
                return cached
        resp = self.service.users().settings().filters().list(userId="me").execute()
        flt = resp.get("filter", resp.get("filters", []))
        if use_cache:
            self.cfg_put_json("filters", flt)
        return flt

    def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        body = {"criteria": criteria, "action": action}
        return self.service.users().settings().filters().create(userId="me", body=body).execute()

    def delete_filter(self, filter_id: str) -> None:
        self.service.users().settings().filters().delete(userId="me", id=filter_id).execute()

    def list_forwarding_addresses(self) -> List[str]:
        infos = self.list_forwarding_addresses_info()
        return [i.get("forwardingEmail") for i in infos if i.get("forwardingEmail")]

    def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
        resp = self.service.users().settings().forwardingAddresses().list(userId="me").execute()
        return resp.get("forwardingAddresses", [])

    def get_verified_forwarding_addresses(self) -> List[str]:
        infos = self.list_forwarding_addresses_info()
        return [i.get("forwardingEmail") for i in infos if i.get("verificationStatus") == "accepted"]

    def create_forwarding_address(self, email: str) -> Dict[str, Any]:
        body = {"forwardingEmail": email}
        # Note: This requires recipient verification outside of this tool.
        return self.service.users().settings().forwardingAddresses().create(userId="me", body=body).execute()

    # --- Account-level auto-forwarding settings ---
    def get_auto_forwarding(self) -> Dict[str, Any]:
        """Return Gmail account-level auto-forwarding settings.

        Includes keys like enabled, emailAddress, and disposition.
        """
        return self.service.users().settings().getAutoForwarding(userId="me").execute()

    def update_auto_forwarding(
        self,
        *,
        enabled: bool,
        email: Optional[str] = None,
        disposition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update Gmail account-level auto-forwarding settings.

        disposition: one of leaveInInbox, archive, trash, markRead
        """
        body: Dict[str, Any] = {"enabled": bool(enabled)}
        if email:
            body["emailAddress"] = str(email)
        if disposition:
            body["disposition"] = str(disposition)
        return self.service.users().settings().updateAutoForwarding(userId="me", body=body).execute()

    # --- Messages metadata helpers (with optional caching) ---
    def get_message_metadata(self, msg_id: str, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache and self.cache:
            m = self.cache.get_meta(msg_id)
            if isinstance(m, dict):
                return m
        msg = self.service.users().messages().get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=[
                "From",
                "To",
                "Subject",
                "List-Unsubscribe",
                "List-Id",
                "Precedence",
                "Auto-Submitted",
            ],
        ).execute()
        if use_cache and self.cache:
            try:
                self.cache.put_meta(msg_id, msg)
            except Exception:  # nosec B110 - non-critical cache write
                pass
        return msg

    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for mid in ids:
            try:
                out.append(self.get_message_metadata(mid, use_cache=use_cache))
            except Exception:  # nosec B112 - skip on error
                continue
        return out

    @staticmethod
    def headers_to_dict(msg: Dict[str, Any]) -> Dict[str, str]:
        hdrs: Dict[str, str] = {}
        try:
            for h in ((msg.get("payload") or {}).get("headers") or []):
                name = h.get("name")
                value = h.get("value")
                if name and value is not None:
                    hdrs[name.lower()] = value
        except Exception:  # nosec B110 - malformed headers
            pass
        return hdrs

    # --- Message content helpers ---
    def get_message(self, msg_id: str, fmt: str = "full") -> Dict[str, Any]:
        return self.service.users().messages().get(userId="me", id=msg_id, format=fmt).execute()

    @staticmethod
    def _decode_message_data(data: str) -> str:
        """Decode base64-encoded message data."""
        import base64
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:  # nosec B110 - best-effort decoding
            return ""

    @staticmethod
    def _walk_message_parts(payload: Dict[str, Any]) -> list[dict]:
        """Recursively walk message parts to find all MIME parts."""
        parts = payload.get("parts") or []
        out = []
        for part in parts:
            out.append(part)
            out.extend(GmailClient._walk_message_parts(part))
        return out

    def _find_text_parts(self, parts: list[dict]) -> tuple[Optional[str], Optional[str]]:
        """Extract text/plain and text/html content from message parts.

        Returns:
            Tuple of (plain_text, html_text) where either may be None
        """
        text_plain = None
        text_html = None
        for part in parts:
            mt = (part.get("mimeType") or "").lower()
            body = part.get("body") or {}
            data = body.get("data")
            if not data:
                continue
            decoded = self._decode_message_data(data)
            if mt == "text/plain" and not text_plain:
                text_plain = decoded
            elif mt == "text/html" and not text_html:
                text_html = decoded
        return text_plain, text_html

    def get_message_text(self, msg_id: str) -> str:
        """Return a best-effort text content from a message (plain preferred, else HTML stripped)."""
        msg = self.get_message(msg_id, fmt="full")
        payload = msg.get("payload") or {}

        # Gather all MIME parts (single-part + multipart)
        candidates = [payload] + self._walk_message_parts(payload)

        # Extract text content
        text_plain, text_html = self._find_text_parts(candidates)

        # Prefer plain text, fallback to HTML (converted), then snippet
        if text_plain:
            return text_plain
        if text_html:
            return html_to_text(text_html)
        return (msg.get("snippet") or "").strip()

    # Note: filter methods defined above with optional caching; avoid duplicate declarations.

    # --- Sending and drafts ---
    def _encode_message_raw(self, raw_bytes: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    def send_message_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"raw": self._encode_message_raw(raw_bytes)}
        if thread_id:
            body["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=body).execute()

    def create_draft_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"raw": self._encode_message_raw(raw_bytes)}
        if thread_id:
            msg["threadId"] = thread_id
        body = {"message": msg}
        return self.service.users().drafts().create(userId="me", body=body).execute()
