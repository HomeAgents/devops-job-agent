from __future__ import annotations

import os
import platform
from unittest import mock

from orchestrator import vm_lifecycle


def test_vm_lifecycle_disabled_when_skip_vm(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_SKIP_VM", "1")
    monkeypatch.delenv("ORCHESTRATOR_VM_AUTOSTART", raising=False)
    assert vm_lifecycle.vm_lifecycle_enabled() is False


def test_vm_lifecycle_off_on_darwin_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_SKIP_VM", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_VM_AUTOSTART", raising=False)
    with mock.patch.object(platform, "system", return_value="Darwin"):
        assert vm_lifecycle.vm_lifecycle_enabled() is False


def test_vm_lifecycle_on_when_explicit_autostart(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_VM_AUTOSTART", "1")
    with mock.patch.object(platform, "system", return_value="Darwin"):
        assert vm_lifecycle.vm_lifecycle_enabled() is True


def test_ensure_vm_started_skips_az_on_mac(monkeypatch) -> None:
    monkeypatch.delenv("ORCHESTRATOR_VM_AUTOSTART", raising=False)
    with mock.patch.object(platform, "system", return_value="Darwin"):
        with mock.patch.object(vm_lifecycle, "subprocess") as sp:
            vm_lifecycle.ensure_vm_started()
            sp.run.assert_not_called()
