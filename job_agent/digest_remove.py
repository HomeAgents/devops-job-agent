"""Signed remove/restore links in digest email + local HTTP handler."""

from __future__ import annotations

import base64
import collections
import hashlib
import hmac
import html
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from job_agent.ignore_store import (
    add_removed_record,
    ignore_store_path,
    job_to_removed_record,
    load_removed_records,
    restore_removed_link,
)
from job_agent.settings import get_setting
from job_agent.util import normalize_url

Action = Literal["remove", "restore", "apply", "set_status"]

_SERVER_LOCK = threading.Lock()
_SERVER: Optional[ThreadingHTTPServer] = None
_SERVER_THREAD: Optional[threading.Thread] = None


def _digest_remove_block(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("digest_remove")
    return block if isinstance(block, dict) else {}


def digest_remove_enabled(cfg: Dict[str, Any]) -> bool:
    block = _digest_remove_block(cfg)
    return bool(block.get("enabled", True))


def job_tracker_digest_columns_enabled(cfg: Dict[str, Any]) -> bool:
    """Show Last updated + Status columns in digest email."""
    from job_agent.job_tracker_excel import job_tracker_enabled

    return job_tracker_enabled(cfg)


def job_tracker_apply_enabled(cfg: Dict[str, Any]) -> bool:
    """Whether /apply «Yes» links are offered (off by default; use Status links)."""
    if not job_tracker_digest_columns_enabled(cfg):
        return False
    block = cfg.get("job_tracker")
    if isinstance(block, dict) and "apply_links_enabled" in block:
        return bool(block.get("apply_links_enabled"))
    return False


def remove_secret(cfg: Dict[str, Any]) -> str:
    block = _digest_remove_block(cfg)
    base_secret = ""
    for key in ("secret",):
        v = (block.get(key) or "").strip()
        if v:
            base_secret = v
            break
    if not base_secret:
        env = get_setting("JOB_AGENT_REMOVE_SECRET", "DIGEST_REMOVE_SECRET").strip()
        if env:
            base_secret = env
    if not base_secret:
        print(
            "WARNING: No HMAC secret configured for digest action links. "
            "Set JOB_AGENT_REMOVE_SECRET env var or digest_remove.secret in config. "
            "Using auto-derived fallback (predictable from filesystem path).",
            file=sys.stderr,
        )
        path = ignore_store_path(cfg)
        base_secret = hashlib.sha256(f"job-agent-remove:{path}".encode()).hexdigest()
    user_email = _user_email_from_cfg(cfg).strip().lower()
    if user_email:
        return hashlib.sha256(f"{base_secret}:{user_email}".encode()).hexdigest()
    return base_secret


def remove_base_url(cfg: Dict[str, Any]) -> str:
    block = _digest_remove_block(cfg)
    raw = (block.get("base_url") or "").strip()
    if raw:
        return raw.rstrip("/")
    port = int(block.get("port") or 8791)
    host = (block.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{port}"


def remove_listen_host_port(cfg: Dict[str, Any]) -> Tuple[str, int]:
    block = _digest_remove_block(cfg)
    port = int(block.get("port") or 8791)
    host = (block.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    return host, port


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _user_email_from_cfg(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("_user_email") or os.environ.get("EMAIL_TO") or "").strip().lower()


def _sanitize_email(email: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", email.strip().lower())


def orchestrator_users_root() -> Path:
    return Path(os.getenv("ORCHESTRATOR_DATA_DIR", str(Path.home() / "orchestrator-data"))) / "users"


def _load_user_cfg_from_path(cfg_path: Path) -> Optional[Dict[str, Any]]:
    if not cfg_path.is_file():
        return None
    try:
        from job_agent.main import load_config

        return load_config(cfg_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def find_user_cfg_by_email(email: str) -> Optional[Dict[str, Any]]:
    safe = _sanitize_email(email)
    if not safe:
        return None
    return _load_user_cfg_from_path(orchestrator_users_root() / safe / "config.json")


def _link_in_jobs_db(link: str, db_path: Path) -> bool:
    from job_agent import db as job_db

    if not link or not db_path.is_file():
        return False
    conn = job_db.connect(db_path)
    try:
        return job_db.load_job_by_link(conn, link) is not None
    finally:
        conn.close()


def find_user_cfg_for_link(link: str) -> Optional[Dict[str, Any]]:
    key = normalize_url((link or "").strip())
    if not key:
        return None
    users_root = orchestrator_users_root()
    if not users_root.is_dir():
        return None
    for user_dir in sorted(users_root.iterdir()):
        if not user_dir.is_dir():
            continue
        cfg_path = user_dir / "config.json"
        jobs_db = user_dir / "jobs.db"
        if not cfg_path.is_file():
            continue
        if jobs_db.is_file() and _link_in_jobs_db(key, jobs_db):
            return _load_user_cfg_from_path(cfg_path)
    return None


def resolve_cfg_for_token(token: str, default_cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[str]]:
    """Verify token and pick the per-user config (multi-tenant orchestrator)."""
    payload, err = _decode_action_token(token, default_cfg)
    if err or not payload:
        return default_cfg, None, err
    user = str(payload.get("user") or "").strip().lower()
    if user:
        cfg = find_user_cfg_by_email(user)
        if cfg:
            return cfg, payload, None
    link = normalize_url(str(payload.get("link") or "").strip())
    if link:
        cfg = find_user_cfg_for_link(link)
        if cfg:
            return cfg, payload, None
    return default_cfg, payload, None


def sign_action_token(
    link: str,
    cfg: Dict[str, Any],
    *,
    action: Action = "remove",
    status: str = "",
    ttl_days: int = 90,
    user_email: str = "",
) -> str:
    payload: Dict[str, Any] = {
        "link": normalize_url(link.strip()),
        "action": action,
        "exp": int(time.time()) + max(1, ttl_days) * 86400,
    }
    if status.strip():
        payload["status"] = status.strip()
    email = (user_email or _user_email_from_cfg(cfg)).strip().lower()
    if email:
        payload["user"] = email
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(remove_secret(cfg).encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def _decode_action_token(token: str, cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    token = (token or "").strip()
    if "." not in token:
        return None, "Invalid token"
    body, sig = token.rsplit(".", 1)
    expected_sig = hmac.new(remove_secret(cfg).encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected_sig, sig):
        return None, "Invalid signature"
    try:
        payload = json.loads(_b64url_decode(body))
    except (json.JSONDecodeError, ValueError):
        return None, "Invalid token payload"
    if not isinstance(payload, dict):
        return None, "Invalid token payload"
    exp = int(payload.get("exp") or 0)
    if exp and time.time() > exp:
        return None, "This link expired"
    return payload, None


def verify_action_token(token: str, cfg: Dict[str, Any], *, expected: Action) -> Tuple[Optional[str], Optional[str]]:
    payload, err = _decode_action_token(token, cfg)
    if err or not payload:
        return None, err
    link = normalize_url(str(payload.get("link") or "").strip())
    if not link:
        return None, "Missing job link"
    action = str(payload.get("action") or "remove").strip().lower()
    if action != expected:
        return None, f"Invalid action (expected {expected})"
    return link, None


def verify_set_status_token(token: str, cfg: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    payload, err = _decode_action_token(token, cfg)
    if err or not payload:
        return None, None, err
    link = normalize_url(str(payload.get("link") or "").strip())
    if not link:
        return None, None, "Missing job link"
    action = str(payload.get("action") or "").strip().lower()
    if action != "set_status":
        return None, None, "Invalid action (expected set_status)"
    status = str(payload.get("status") or "").strip()
    if not status:
        return None, None, "Missing status"
    return link, status, None


def build_remove_yes_url(link: str, cfg: Dict[str, Any]) -> str:
    token = sign_action_token(link, cfg, action="remove")
    return f"{remove_base_url(cfg)}/remove?t={token}"


def build_restore_url(link: str, cfg: Dict[str, Any]) -> str:
    token = sign_action_token(link, cfg, action="restore")
    return f"{remove_base_url(cfg)}/restore?t={token}"


def build_apply_yes_url(link: str, cfg: Dict[str, Any]) -> str:
    token = sign_action_token(link, cfg, action="apply")
    return f"{remove_base_url(cfg)}/apply?t={token}"


def build_set_status_url(link: str, status: str, cfg: Dict[str, Any]) -> str:
    from job_agent.job_tracker_excel import normalize_status_label

    canonical = normalize_status_label(status, cfg, strict=True)
    token = sign_action_token(link, cfg, action="set_status", status=canonical)
    return f"{remove_base_url(cfg)}/status?t={token}"


def _html_page(title: str, body: str, *, status: int = 200, cfg: Optional[Dict[str, Any]] = None) -> bytes:
    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;max-width:42em;margin:2em auto;line-height:1.5;">
<h1>{title}</h1>
{body}
<p style="color:#999;font-size:12px;">Job Agent</p>
</body></html>"""
    return page.encode("utf-8")


def _apply_remove(link: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    from job_agent import db as job_db
    from job_agent.util import job_link_identity

    link = normalize_url(link.strip())
    snapshot: Dict[str, Any] = {"link": link, "link_identity": job_link_identity(link)}
    conn = _db_connect(cfg)
    deleted = 0
    try:
        job = job_db.load_job_by_link(conn, link)
        if job is not None:
            snapshot = job_to_removed_record(job)
        deleted = job_db.delete_jobs_for_posting(conn, link)
    finally:
        conn.close()
    added = add_removed_record(snapshot, cfg)
    title = snapshot.get("title") or link
    root = _project_root(cfg)
    tracker_note = ""
    from job_agent.job_tracker_excel import (
        default_job_tracker_path,
        job_snapshot_from_removed_record,
        job_tracker_enabled,
        removed_status_label,
        set_job_tracker_status,
    )

    if job_tracker_enabled(cfg):
        try:
            set_job_tracker_status(
                link,
                removed_status_label(cfg),
                cfg,
                root=root,
                job_snapshot=job_snapshot_from_removed_record(snapshot),
            )
            tracker_note = (
                f"<p style=\"font-size:13px;color:#666;\">Status updated to "
                f"<strong>{html.escape(removed_status_label(cfg))}</strong>.</p>"
            )
        except ValueError:
            tracker_note = ""
    if added:
        return (
            True,
            f"<p><strong>Removed.</strong> «{html.escape(str(title))}» will not appear in "
            f"future digest emails.</p>"
            f"{tracker_note}",
        )
    return (
        False,
        f"<p><strong>Already removed.</strong> «{html.escape(str(title))}» was already hidden "
        f"from future digests.</p>"
        f"{tracker_note}",
    )


def _project_root(cfg: Dict[str, Any]) -> "Path":
    from pathlib import Path

    raw = str(cfg.get("_project_root") or "").strip()
    return Path(raw).resolve() if raw else Path.cwd().resolve()


def _jobs_db_path(cfg: Dict[str, Any]) -> "Path":
    from pathlib import Path

    explicit = str(cfg.get("_jobs_db") or "").strip()
    if explicit:
        return Path(explicit)
    return _project_root(cfg) / "jobs.db"


def _db_connect(cfg: Dict[str, Any]):
    from job_agent import db as job_db

    return job_db.connect(_jobs_db_path(cfg))


def _apply_set_status(link: str, status: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    from job_agent.job_tracker_excel import default_job_tracker_path, set_job_tracker_status

    root = _project_root(cfg)
    snapshot: Dict[str, Any] = {"Link": link, "link": link}
    from job_agent import db as job_db

    conn = _db_connect(cfg)
    try:
        job = job_db.load_job_by_link(conn, link)
        if job is not None:
            snapshot = {
                "Job Title": job.title,
                "Company": job.company,
                "Location": job.location,
                "Link": job.link,
                "Source": job.source,
                "Network": "",
            }
    finally:
        conn.close()
    try:
        canonical = set_job_tracker_status(link, status, cfg, root=root, job_snapshot=snapshot)
    except ValueError as exc:
        return False, f"<p>{html.escape(str(exc))}</p>"
    path = default_job_tracker_path(root, cfg)
    tracker_msg = (
        f"<p><strong>Status updated.</strong> Set to <strong>{html.escape(canonical)}</strong>.</p>"
        f"<p style=\"font-size:13px;color:#666;\">This will be reflected in your next digest email.</p>"
    )
    return True, tracker_msg


def _apply_mark_applied(link: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    from job_agent.job_tracker_excel import record_job_apply

    snapshot: Dict[str, Any] = {"link": link, "Link": link}
    from job_agent import db as job_db

    conn = _db_connect(cfg)
    try:
        job = job_db.load_job_by_link(conn, link)
        if job is not None:
            snapshot = {
                "Job Title": job.title,
                "Company": job.company,
                "Location": job.location,
                "Link": job.link,
                "Source": job.source,
                "Network": "",
            }
    finally:
        conn.close()
    when = record_job_apply(link, snapshot, cfg, root=_project_root(cfg))
    title = snapshot.get("Job Title") or link
    return True, (
        f"<p><strong>Marked applied.</strong> «{html.escape(str(title))}» — Status set to "
        f"<strong>In Progress</strong>.</p>"
        f"<p style=\"font-size:13px;color:#666;\">This will be reflected in your next digest email.</p>"
    )


def _apply_restore(link: str, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    from job_agent import db as job_db
    from job_agent.ignore_store import record_to_job

    snapshot = restore_removed_link(link, cfg)
    if snapshot is None:
        return False, "<p><strong>Not found.</strong> This job was not on your removed list.</p>"
    job = record_to_job(snapshot)
    conn = _db_connect(cfg)
    try:
        job_db.upsert_jobs(conn, [job], mark_emailed=False)
        conn.execute("UPDATE jobs SET emailed_at = NULL WHERE link = ?", (normalize_url(job.link),))
        conn.commit()
    finally:
        conn.close()
    title = snapshot.get("title") or job.title or link
    return (
        True,
        f"<p><strong>Restored.</strong> «{html.escape(str(title))}» will return to "
        "<strong>Jobs in this digest</strong> on the next email (within the usual "
        f"{int((cfg.get('digest_include_jobs_seen_within_days') or 2))}-day window).</p>",
    )


_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_rate_lock = threading.Lock()
_rate_hits: Dict[str, collections.deque] = {}


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        dq = _rate_hits.get(ip)
        if dq is None:
            dq = collections.deque()
            _rate_hits[ip] = dq
        while dq and dq[0] < now - _RATE_LIMIT_WINDOW:
            dq.popleft()
        if len(dq) >= _RATE_LIMIT_MAX:
            return True
        dq.append(now)
    return False


class _RemoveHandler(BaseHTTPRequestHandler):
    cfg: Dict[str, Any] = {}

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[digest-remove] {self.address_string()} {fmt % args}", file=sys.stderr)

    def _send_html(self, status: int, title: str, body: str) -> None:
        data = _html_page(title, body, status=status, cfg=self.cfg)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route_path(self, parsed) -> str:
        path = (parsed.path or "/").split("?")[0].rstrip("/").lower() or "/"
        return path

    def do_GET(self) -> None:
        if len(self.path) > 8192:
            self._send_html(414, "URI too long", "<p>Request URI is too long.</p>")
            return
        if _rate_limited(self.client_address[0]):
            self._send_html(429, "Too many requests", "<p>Rate limit exceeded. Try again in a minute.</p>")
            return
        try:
            self._do_get_routed()
        except Exception as exc:
            print(f"[digest-remove] handler error: {exc}", file=sys.stderr)
            try:
                self._send_html(
                    500,
                    "Server error",
                    f"<p>Something went wrong: {html.escape(str(exc))}</p>",
                )
            except Exception:
                pass

    def _do_get_routed(self) -> None:
        parsed = urlparse(self.path)
        route = self._route_path(parsed)
        if route == "/health":
            users = 0
            if orchestrator_users_root().is_dir():
                users = sum(1 for d in orchestrator_users_root().iterdir() if d.is_dir())
            self._send_html(
                200,
                "OK",
                "<p>Job Agent action server is running.</p>",
            )
            return
        qs = parse_qs(parsed.query)
        token = (qs.get("t") or [""])[0]
        if route == "/remove":
            cfg, payload, err = resolve_cfg_for_token(token, self.cfg)
            if err or not payload:
                self._send_html(400, "Could not remove", f"<p>{err or 'Unknown error'}.</p>")
                return
            if str(payload.get("action") or "").strip().lower() != "remove":
                self._send_html(400, "Could not remove", "<p>Invalid action (expected remove).</p>")
                return
            link = normalize_url(str(payload.get("link") or ""))
            if not link:
                self._send_html(400, "Could not remove", "<p>Missing job link.</p>")
                return
            _, msg = _apply_remove(link, cfg)
            self._send_html(200, "Job hidden", msg)
            return
        if route == "/restore":
            cfg, payload, err = resolve_cfg_for_token(token, self.cfg)
            if err or not payload:
                self._send_html(400, "Could not restore", f"<p>{err or 'Unknown error'}.</p>")
                return
            if str(payload.get("action") or "").strip().lower() != "restore":
                self._send_html(400, "Could not restore", "<p>Invalid action (expected restore).</p>")
                return
            link = normalize_url(str(payload.get("link") or ""))
            if not link:
                self._send_html(400, "Could not restore", "<p>Missing job link.</p>")
                return
            _, msg = _apply_restore(link, cfg)
            self._send_html(200, "Job restored", msg)
            return
        if route == "/apply":
            cfg, payload, err = resolve_cfg_for_token(token, self.cfg)
            if err or not payload:
                self._send_html(400, "Could not mark applied", f"<p>{err or 'Unknown error'}.</p>")
                return
            if str(payload.get("action") or "").strip().lower() != "apply":
                self._send_html(400, "Could not mark applied", "<p>Invalid action (expected apply).</p>")
                return
            link = normalize_url(str(payload.get("link") or ""))
            if not link:
                self._send_html(400, "Could not mark applied", "<p>Missing job link.</p>")
                return
            _, msg = _apply_mark_applied(link, cfg)
            self._send_html(200, "Marked applied", msg)
            return
        if route == "/status":
            cfg, payload, err = resolve_cfg_for_token(token, self.cfg)
            if err or not payload:
                self._send_html(400, "Could not update status", f"<p>{err or 'Unknown error'}.</p>")
                return
            if str(payload.get("action") or "").strip().lower() != "set_status":
                self._send_html(400, "Could not update status", "<p>Invalid action (expected set_status).</p>")
                return
            link = normalize_url(str(payload.get("link") or ""))
            status = str(payload.get("status") or "").strip()
            if not link or not status:
                self._send_html(400, "Could not update status", "<p>Missing job link or status.</p>")
                return
            _, msg = _apply_set_status(link, status, cfg)
            self._send_html(200, "Status updated", msg)
            return
        self._send_html(404, "Not found", "<p>Unknown path.</p>")


def _health_check(cfg: Dict[str, Any], timeout: float = 0.6) -> bool:
    host, port = remove_listen_host_port(cfg)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _server_has_tracker_routes(cfg: Dict[str, Any], timeout: float = 0.8) -> bool:
    """True if HTTP handler exposes /apply and /status (not an old remove-only process)."""
    import urllib.error
    import urllib.request

    for path in ("/apply", "/status"):
        url = f"{remove_base_url(cfg)}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status >= 500:
                    return False
            continue
        except urllib.error.HTTPError as exc:
            if exc.code not in (400, 405):
                return False
        except OSError:
            return False
    return True


def start_remove_server(cfg: Dict[str, Any], *, background: bool = True) -> ThreadingHTTPServer:
    global _SERVER, _SERVER_THREAD
    with _SERVER_LOCK:
        if _SERVER is not None:
            return _SERVER
        host, port = remove_listen_host_port(cfg)
        handler_cls = type("CfgRemoveHandler", (_RemoveHandler,), {"cfg": cfg})
        httpd = ThreadingHTTPServer((host, port), handler_cls)
        _SERVER = httpd
        if background:
            thread = threading.Thread(target=httpd.serve_forever, name="digest-remove", daemon=True)
            thread.start()
            _SERVER_THREAD = thread
        return httpd


def _stop_background_server() -> None:
    global _SERVER, _SERVER_THREAD
    with _SERVER_LOCK:
        if _SERVER is not None:
            try:
                _SERVER.shutdown()
            except Exception:
                pass
            _SERVER = None
            _SERVER_THREAD = None


def _remove_server_log_path(cfg: Dict[str, Any]) -> "Path":
    from pathlib import Path

    return ignore_store_path(cfg).parent / "digest-remove-server.log"


def _spawn_detached_remove_server(cfg: Dict[str, Any]) -> bool:
    """Start remove/status server in a separate process (survives after digest exits)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = _project_root(cfg)
    app_root = Path(__file__).resolve().parent.parent
    run_py = app_root / "run.py"
    if not run_py.is_file():
        run_py = root / "run.py"
    if not run_py.is_file():
        print(f"digest-remove: cannot find {run_py}", file=sys.stderr)
        return False
    log_path = _remove_server_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    config_path = str(cfg.get("_config_path") or os.environ.get("JOB_AGENT_CONFIG") or "").strip()
    if config_path:
        env["JOB_AGENT_CONFIG"] = config_path
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            subprocess.Popen(
                [sys.executable, str(run_py), "--digest-remove-server"],
                cwd=str(app_root if (app_root / "job_agent").is_dir() else root),
                env=env,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
    except OSError as exc:
        print(f"digest-remove server failed to spawn: {exc}", file=sys.stderr)
        return False
    for _ in range(24):
        time.sleep(0.25)
        if _health_check(cfg, timeout=0.8) and _server_has_tracker_routes(cfg, timeout=0.8):
            print(
                f"Digest remove/status server running on {remove_base_url(cfg)} "
                f"(log: {log_path})",
                file=sys.stderr,
            )
            return True
    print(
        f"digest-remove server did not respond on {remove_base_url(cfg)} "
        f"(see {log_path})",
        file=sys.stderr,
    )
    return False


def ensure_remove_server_running(cfg: Dict[str, Any]) -> bool:
    if not digest_remove_enabled(cfg):
        return False
    if _health_check(cfg) and _server_has_tracker_routes(cfg):
        return True
    if _health_check(cfg) and not _server_has_tracker_routes(cfg):
        print(
            "Digest server on port is outdated (no /status). Restart the remove server.",
            file=sys.stderr,
        )
        _stop_background_server()
    _stop_background_server()
    return _spawn_detached_remove_server(cfg)


def run_remove_server_forever(cfg: Dict[str, Any]) -> None:
    host, port = remove_listen_host_port(cfg)
    httpd = start_remove_server(cfg, background=False)
    print(f"Digest remove/restore/apply server on http://{host}:{port} (Ctrl+C to stop)", file=sys.stderr)
    print(f"Ignore store: {ignore_store_path(cfg)}", file=sys.stderr)
    print(f"Removed jobs: {len(load_removed_records(cfg))}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


# Backward-compatible alias
verify_remove_token = lambda token, cfg: verify_action_token(token, cfg, expected="remove")
sign_remove_token = lambda link, cfg, **kw: sign_action_token(link, cfg, action="remove", **kw)
