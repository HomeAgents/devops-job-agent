"""Cloud-side inbox poll: wake vm-home-agents when actionable UNSEEN mail waits."""

from __future__ import annotations

import email
import imaplib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from email.utils import parseaddr
from typing import Any

from orchestrator.email_client import InboundMail, decode_subject
from orchestrator.email_filters import is_ignored_inbound

log = logging.getLogger(__name__)

_ARM_SCOPE = "https://management.azure.com/.default"
_RUNNING = frozenset({"PowerState/running", "PowerState/starting"})


def _imap_credentials() -> tuple[str, str]:
    user = (
        os.getenv("ORCHESTRATOR_IMAP_USER")
        or os.getenv("GMAIL_EMAIL")
        or os.getenv("ORCHESTRATOR_SMTP_USER")
        or ""
    ).strip()
    password = (
        os.getenv("ORCHESTRATOR_IMAP_PASSWORD")
        or os.getenv("GMAIL_APP_PASSWORD")
        or os.getenv("ORCHESTRATOR_SMTP_PASSWORD")
        or ""
    ).strip()
    if not user or not password:
        raise RuntimeError("Missing IMAP credentials (GMAIL_EMAIL + GMAIL_APP_PASSWORD).")
    return user, password


def _vm_settings() -> tuple[str, str, str]:
    sub = (os.getenv("AZURE_SUBSCRIPTION_ID") or "").strip()
    rg = (os.getenv("AZURE_VM_RG") or "rg-home-agents").strip()
    name = (os.getenv("AZURE_VM_NAME") or "vm-home-agents").strip()
    if not sub:
        raise RuntimeError("Missing AZURE_SUBSCRIPTION_ID.")
    return sub, rg, name


def _parse_header_fields(raw: bytes) -> tuple[str, str, str]:
    msg = email.message_from_bytes(raw)
    _, from_addr = parseaddr(msg.get("From", ""))
    subject = msg.get("Subject") or ""
    message_id = (msg.get("Message-ID") or "").strip()
    return from_addr.lower(), subject, message_id


def fetch_unseen_envelopes(*, max_messages: int = 30) -> list[InboundMail]:
    """Fetch UNSEEN message headers only (does not mark as read)."""
    imap_user, imap_pass = _imap_credentials()
    host = os.getenv("ORCHESTRATOR_IMAP_HOST", "imap.gmail.com")
    out: list[InboundMail] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(imap_user, imap_pass)
        imap.select("INBOX")
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return out
        nums = data[0].split()[-max_messages:]
        for num in nums:
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            part = msg_data[0]
            raw = part[1] if isinstance(part, tuple) and len(part) > 1 else b""
            if not raw:
                continue
            from_addr, subject, message_id = _parse_header_fields(raw)
            if not from_addr:
                continue
            out.append(
                InboundMail(
                    message_id=message_id or f"unseen-{num.decode()}",
                    from_email=from_addr,
                    subject=decode_subject(subject),
                    body_text="",
                    attachments=[],
                )
            )
    return out


def has_actionable_unseen(*, max_messages: int = 30) -> tuple[bool, list[str]]:
    """Return (should_wake, debug_reasons)."""
    reasons: list[str] = []
    envelopes = fetch_unseen_envelopes(max_messages=max_messages)
    if not envelopes:
        return False, ["no_unseen"]
    for mail in envelopes:
        if is_ignored_inbound(mail):
            reasons.append(f"skip {mail.from_email!r} {mail.subject[:60]!r}")
            continue
        reasons.append(f"actionable {mail.from_email!r} {mail.subject[:60]!r}")
        return True, reasons
    return False, reasons


def _arm_token() -> str:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential().get_token(_ARM_SCOPE).token


def _arm_request(method: str, url: str, *, token: str | None = None, body: bytes | None = None) -> Any:
    tok = token or _arm_token()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {tok}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"ARM {method} {url} failed ({exc.code}): {detail}") from exc


def vm_power_state() -> str:
    sub, rg, name = _vm_settings()
    url = (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.Compute/virtualMachines/{name}"
        f"?$expand=instanceView&api-version=2024-07-01"
    )
    vm = _arm_request("GET", url)
    statuses = (vm or {}).get("properties", {}).get("instanceView", {}).get("statuses") or []
    for st in statuses:
        code = str(st.get("code") or "")
        if code.startswith("PowerState/"):
            return code
    return "PowerState/unknown"


def _start_via_logic_app() -> bool:
    url = (os.getenv("WAKE_LOGIC_APP_URL") or "").strip()
    if not url.startswith("https://"):
        return False
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        log.warning("Logic App wake failed (%s): %s", exc.code, exc.read().decode(errors="replace"))
        return False


def start_vm_if_needed() -> tuple[bool, str]:
    """Start VM when not running/starting. Returns (started_or_already_up, detail)."""
    state = vm_power_state()
    if state in _RUNNING:
        return False, f"already_{state}"
    if _start_via_logic_app():
        return True, "started_via_logic_app"
    sub, rg, name = _vm_settings()
    url = (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.Compute/virtualMachines/{name}/start?api-version=2024-07-01"
    )
    _arm_request("POST", url, body=b"{}")
    return True, f"started_from_{state}"


def run_wake_cycle() -> dict[str, Any]:
    """Timer entrypoint: poll Gmail UNSEEN; start VM if real user mail is waiting."""
    t0 = time.time()
    result: dict[str, Any] = {"ok": True, "started": False}
    try:
        actionable, reasons = has_actionable_unseen()
        result["actionable_unseen"] = actionable
        result["reasons"] = reasons
        if not actionable:
            result["detail"] = "no_actionable_unseen"
            return result
        try:
            result["vm_state_before"] = vm_power_state()
        except Exception as exc:
            log.warning("Could not read VM power state: %s", exc)
            result["vm_state_before"] = "unknown"
        started, detail = start_vm_if_needed()
        result["started"] = started
        result["detail"] = detail
        if started:
            result["vm_state_after"] = "starting"
        else:
            result["vm_state_after"] = result.get("vm_state_before", "unknown")
    except Exception as exc:
        log.exception("wake cycle failed")
        result["ok"] = False
        result["error"] = str(exc)
    finally:
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
    return result
