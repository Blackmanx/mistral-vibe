from __future__ import annotations

import threading
import time

import pytest

from vibe.app_server._power import (
    _LINUX_INHIBIT_WHAT,
    SleepPreventer,
    _windows_execution_state,
    _wsl_powershell_script,
    is_wsl,
)
from vibe.core.config.models import SleepPreventionMode


class FakeAssertion:
    def __init__(self, mode: SleepPreventionMode) -> None:
        self.mode = mode
        self.released = threading.Event()

    def release(self) -> None:
        self.released.set()


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met in time")


def test_off_mode_holds_nothing() -> None:
    started: list[SleepPreventionMode] = []
    preventer = SleepPreventer(lambda mode: started.append(mode) or FakeAssertion(mode))
    try:
        preventer.set_active("session", active=True, mode=SleepPreventionMode.OFF)
    finally:
        preventer.close()
    assert started == []


def test_strongest_mode_is_held_until_the_last_owner_leaves() -> None:
    assertions: list[FakeAssertion] = []
    preventer = SleepPreventer(
        lambda mode: assertions.append(FakeAssertion(mode)) or assertions[-1]
    )
    try:
        preventer.set_active("parent", active=True, mode=SleepPreventionMode.IDLE)
        wait_until(lambda: len(assertions) == 1)
        assert assertions[0].mode is SleepPreventionMode.IDLE

        preventer.set_active("child", active=True, mode=SleepPreventionMode.DISPLAY)
        wait_until(lambda: len(assertions) == 2)
        assert assertions[0].released.is_set()
        assert assertions[1].mode is SleepPreventionMode.DISPLAY

        preventer.set_active("parent", active=False, mode=SleepPreventionMode.OFF)
        time.sleep(0.1)
        assert not assertions[1].released.is_set()

        preventer.set_active("child", active=False, mode=SleepPreventionMode.OFF)
        wait_until(assertions[1].released.is_set)
    finally:
        preventer.close()


def test_failed_mode_is_not_retried_until_it_changes() -> None:
    attempts: list[SleepPreventionMode] = []
    preventer = SleepPreventer(lambda mode: attempts.append(mode) or None)
    try:
        preventer.set_active("session", active=True, mode=SleepPreventionMode.DISPLAY)
        wait_until(lambda: len(attempts) == 1)

        preventer.set_active("session", active=True, mode=SleepPreventionMode.DISPLAY)
        time.sleep(0.1)
        assert attempts == [SleepPreventionMode.DISPLAY]

        preventer.set_active("session", active=True, mode=SleepPreventionMode.SYSTEM)
        wait_until(lambda: len(attempts) == 2)
        assert attempts == [SleepPreventionMode.DISPLAY, SleepPreventionMode.SYSTEM]
    finally:
        preventer.close()


@pytest.mark.parametrize(
    ("mode", "what"),
    [
        (SleepPreventionMode.IDLE, "idle"),
        (SleepPreventionMode.DISPLAY, "idle"),
        (SleepPreventionMode.SYSTEM, "idle:sleep"),
    ],
)
def test_linux_inhibit_what(mode: SleepPreventionMode, what: str) -> None:
    assert _LINUX_INHIBIT_WHAT[mode] == what


@pytest.mark.parametrize(
    "mode",
    [SleepPreventionMode.IDLE, SleepPreventionMode.DISPLAY, SleepPreventionMode.SYSTEM],
)
def test_windows_execution_state_always_requests_the_system(
    mode: SleepPreventionMode,
) -> None:
    flags = _windows_execution_state(mode)
    assert flags & 0x80000000
    assert flags & 0x00000001
    assert bool(flags & 0x00000002) is (mode is not SleepPreventionMode.IDLE)


def test_wsl_script_holds_and_clears_the_windows_state() -> None:
    script = _wsl_powershell_script(
        _windows_execution_state(SleepPreventionMode.SYSTEM)
    )
    assert "SetThreadExecutionState" in script
    assert "2147483648" in script
    assert "[Console]::In.ReadLine()" in script


def test_wsl_detection_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert is_wsl()
