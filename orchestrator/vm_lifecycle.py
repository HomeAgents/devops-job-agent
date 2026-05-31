from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def vm_lifecycle_enabled() -> bool:
    """Azure VM start/stop — off by default on macOS (home agents run locally)."""
    if _env_bool("ORCHESTRATOR_SKIP_VM", False):
        return False
    if platform.system() == "Darwin" and os.getenv("ORCHESTRATOR_VM_AUTOSTART") is None:
        return False
    return _env_bool("ORCHESTRATOR_VM_AUTOSTART", True)


def activity_file() -> Path:
    p = Path(os.getenv("ORCHESTRATOR_ACTIVITY_FILE", str(Path.home() / "orchestrator-data" / "last_activity")))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def touch_activity() -> None:
    activity_file().write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def idle_minutes() -> float:
    f = activity_file()
    if not f.exists():
        return 9999.0
    try:
        ts = datetime.fromisoformat(f.read_text(encoding="utf-8").strip())
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except (ValueError, OSError):
        return 9999.0


def maybe_stop_vm(idle_limit_min: int = 15) -> bool:
    """Deallocate Azure VM if idle longer than limit. Returns True if stop requested."""
    if not vm_lifecycle_enabled():
        return False
    if not _env_bool("ORCHESTRATOR_VM_AUTOSTOP", True):
        return False
    if idle_minutes() < idle_limit_min:
        return False
    rg = os.getenv("AZURE_VM_RG", "rg-home-agents")
    name = os.getenv("AZURE_VM_NAME", "vm-home-agents")
    try:
        subprocess.run(
            ["az", "vm", "deallocate", "-g", rg, "-n", name, "-o", "none"],
            check=False,
            timeout=120,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_vm_started() -> None:
    if not vm_lifecycle_enabled():
        touch_activity()
        return
    rg = os.getenv("AZURE_VM_RG", "rg-home-agents")
    name = os.getenv("AZURE_VM_NAME", "vm-home-agents")
    try:
        subprocess.run(["az", "vm", "start", "-g", rg, "-n", name, "-o", "none"], check=False, timeout=180)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    touch_activity()
