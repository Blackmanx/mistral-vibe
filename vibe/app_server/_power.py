"""Host power assertions that keep the machine awake during a turn.

Vibe holds an assertion only while at least one turn is running; an idle
session never keeps the machine or the display awake. The backends mirror
oh-my-pi's ``power.sleepPrevention`` levels:

- ``idle`` blocks idle system sleep;
- ``display`` also keeps the display on;
- ``system`` also blocks system sleep.

Linux uses logind and the desktop ``ScreenSaver`` D-Bus services, macOS uses
``caffeinate``, Windows uses ``SetThreadExecutionState`` on a dedicated thread,
and WSL asks the Windows host to do the same through PowerShell interop.
Unsupported hosts degrade to no assertion instead of failing the turn.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
import ctypes
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import queue
import select
import shutil
import subprocess
import sys
import threading
from typing import Any, Protocol, Self

from vibe.core.config.models import SleepPreventionMode

logger = logging.getLogger(__name__)

_REASON = "Vibe is running an agent turn"
_DISPLAY_MODES = frozenset({SleepPreventionMode.DISPLAY, SleepPreventionMode.SYSTEM})
_MODE_STRENGTH = {
    SleepPreventionMode.OFF: 0,
    SleepPreventionMode.IDLE: 1,
    SleepPreventionMode.DISPLAY: 2,
    SleepPreventionMode.SYSTEM: 3,
}
_LINUX_INHIBIT_WHAT = {
    SleepPreventionMode.IDLE: "idle",
    SleepPreventionMode.DISPLAY: "idle",
    SleepPreventionMode.SYSTEM: "idle:sleep",
}

# Windows SetThreadExecutionState flags. ``system`` has no stronger equivalent
# than ``ES_SYSTEM_REQUIRED``; ``display`` adds ``ES_DISPLAY_REQUIRED``.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class PowerAssertion(Protocol):
    """A held platform assertion, released once the last turn ends."""

    def release(self) -> None: ...


class _CompositeAssertion:
    def __init__(self, assertions: Sequence[PowerAssertion]) -> None:
        self._assertions = list(assertions)

    def release(self) -> None:
        for assertion in self._assertions:
            with suppress(Exception):
                assertion.release()
        self._assertions.clear()


class _ProcessAssertion:
    """An assertion held by a helper process, such as macOS ``caffeinate``."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    def release(self) -> None:
        with suppress(OSError):
            self._process.terminate()
        with suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=1.0)
            return
        with suppress(OSError):
            self._process.kill()
        with suppress(Exception):
            self._process.wait(timeout=1.0)


class _Login1Assertion:
    """A logind inhibitor, released by closing its file descriptor."""

    def __init__(self, connection: Any, descriptor: Any) -> None:
        self._connection = connection
        self._descriptor = descriptor

    @classmethod
    def start(cls, what: str) -> Self | None:
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection
        except ImportError:
            logger.debug("jeepney is unavailable; cannot inhibit login1 sleep")
            return None
        connection = None
        try:
            connection = open_dbus_connection(bus="SYSTEM", enable_fds=True)
            reply = connection.send_and_get_reply(
                new_method_call(
                    DBusAddress(
                        "/org/freedesktop/login1",
                        bus_name="org.freedesktop.login1",
                        interface="org.freedesktop.login1.Manager",
                    ),
                    "Inhibit",
                    "ssss",
                    (what, "vibe", _REASON, "block"),
                )
            )
            descriptor = reply.body[0]
        except Exception as exc:
            if connection is not None:
                with suppress(Exception):
                    connection.close()
            logger.debug("login1 sleep inhibition is unavailable: %s", exc)
            return None
        return cls(connection, descriptor)

    def release(self) -> None:
        with suppress(Exception):
            self._descriptor.close()
        with suppress(Exception):
            self._connection.close()


class _ScreenSaverAssertion:
    """A desktop screen-saver inhibitor, freed with ``UnInhibit``."""

    def __init__(
        self,
        connection: Any,
        cookie: int,
        *,
        path: str,
        bus_name: str,
        interface: str,
        uninhibit_method: str,
    ) -> None:
        self._connection = connection
        self._cookie = cookie
        self._path = path
        self._bus_name = bus_name
        self._interface = interface
        self._uninhibit_method = uninhibit_method

    @classmethod
    def start(cls) -> Self | None:
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection
        except ImportError:
            logger.debug("jeepney is unavailable; cannot inhibit the screen saver")
            return None
        # The freedesktop interface covers GNOME, KDE, XFCE and most other
        # desktops; GNOME's own manager is the fallback when it is absent.
        attempts: tuple[tuple[str, str, str, Callable[[Any], Any]], ...] = (
            (
                "/org/freedesktop/ScreenSaver",
                "org.freedesktop.ScreenSaver",
                "org.freedesktop.ScreenSaver",
                lambda address: new_method_call(
                    address, "Inhibit", "ss", ("vibe", _REASON)
                ),
            ),
            (
                "/org/gnome/SessionManager",
                "org.gnome.SessionManager",
                "org.gnome.SessionManager",
                lambda address: new_method_call(
                    address, "Inhibit", "susu", ("vibe", 0, _REASON, 8)
                ),
            ),
        )
        for path, bus_name, interface, message in attempts:
            connection = None
            try:
                connection = open_dbus_connection(bus="SESSION")
                address = DBusAddress(path, bus_name=bus_name, interface=interface)
                reply = connection.send_and_get_reply(message(address))
                cookie = int(reply.body[0])
            except Exception as exc:
                if connection is not None:
                    with suppress(Exception):
                        connection.close()
                logger.debug("Screen saver inhibition via %s failed: %s", bus_name, exc)
                continue
            return cls(
                connection,
                cookie,
                path=path,
                bus_name=bus_name,
                interface=interface,
                uninhibit_method=(
                    "UnInhibit"
                    if interface == "org.freedesktop.ScreenSaver"
                    else "Uninhibit"
                ),
            )
        return None

    def release(self) -> None:
        try:
            from jeepney import DBusAddress, new_method_call

            with suppress(Exception):
                self._connection.send_and_get_reply(
                    new_method_call(
                        DBusAddress(
                            self._path,
                            bus_name=self._bus_name,
                            interface=self._interface,
                        ),
                        self._uninhibit_method,
                        "u",
                        (self._cookie,),
                    )
                )
        finally:
            with suppress(Exception):
                self._connection.close()


class _WindowsAssertion:
    """A thread-affine ``SetThreadExecutionState`` assertion."""

    def __init__(self, release: threading.Event, thread: threading.Thread) -> None:
        self._release = release
        self._thread = thread

    @classmethod
    def start(cls, mode: SleepPreventionMode) -> Self | None:
        release = threading.Event()
        ready = threading.Event()
        acquired: list[bool] = []

        def hold() -> None:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
            kernel32.SetThreadExecutionState.restype = ctypes.c_uint
            changed = kernel32.SetThreadExecutionState(
                ctypes.c_uint(_windows_execution_state(mode))
            )
            acquired.append(bool(changed))
            ready.set()
            release.wait()
            kernel32.SetThreadExecutionState(ctypes.c_uint(_ES_CONTINUOUS))

        thread = threading.Thread(target=hold, name="vibe-power-hold", daemon=True)
        thread.start()
        if not ready.wait(timeout=2.0) or not acquired or not acquired[0]:
            release.set()
            thread.join(timeout=1.0)
            logger.warning("Windows refused the sleep-prevention assertion")
            return None
        return cls(release, thread)

    def release(self) -> None:
        self._release.set()
        self._thread.join(timeout=2.0)


class _WslAssertion:
    """A Windows assertion held through a PowerShell interop process.

    The script blocks on stdin: when Vibe exits, the pipe closes and the
    Windows thread clears its execution state instead of leaking it.
    """

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    @classmethod
    def start(cls, mode: SleepPreventionMode) -> Self | None:
        executable = _windows_powershell()
        if executable is None:
            logger.debug("Windows PowerShell is unavailable for WSL sleep prevention")
            return None
        script = _wsl_powershell_script(_windows_execution_state(mode))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            process = subprocess.Popen(
                [
                    executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-EncodedCommand",
                    encoded,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.debug("Unable to start Windows PowerShell: %s", exc)
            return None
        if not _wait_for_wsl_ready(process):
            _stop_process(process)
            logger.debug("Windows PowerShell did not confirm sleep prevention")
            return None
        return cls(process)

    def release(self) -> None:
        _stop_process(self._process)


def _wait_for_wsl_ready(process: subprocess.Popen[bytes]) -> bool:
    """Wait for the script's ``ready`` marker after it sets the Windows state."""
    stdout = process.stdout
    if stdout is None:
        return False
    try:
        readable, _, _ = select.select([stdout], [], [], 10.0)
        return bool(readable) and stdout.read(5) == b"ready"
    except (OSError, ValueError):
        return False
    finally:
        with suppress(OSError, ValueError):
            stdout.close()


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        with suppress(OSError, ValueError):
            process.stdin.close()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1.0)
        return
    with suppress(OSError):
        process.kill()
    with suppress(Exception):
        process.wait(timeout=1.0)


def _windows_execution_state(mode: SleepPreventionMode) -> int:
    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
    if mode in _DISPLAY_MODES:
        flags |= _ES_DISPLAY_REQUIRED
    return flags


def _wsl_powershell_script(flags: int) -> str:
    return (
        "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices;"
        ' public static class VibePower { [DllImport("kernel32.dll")]'
        " public static extern uint SetThreadExecutionState(uint flags); }';"
        f" $state = [VibePower]::SetThreadExecutionState({flags});"
        " if ($state -eq 0) { exit 1 };"
        " [Console]::Out.Write('ready'); [Console]::Out.Flush();"
        " try { [void][Console]::In.ReadLine() } finally"
        f" {{ [VibePower]::SetThreadExecutionState({_ES_CONTINUOUS}) | Out-Null }}"
    )


def _windows_powershell() -> str | None:
    for name in ("powershell.exe", "pwsh.exe"):
        found = shutil.which(name)
        if found is not None:
            return found
    fallback = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    return str(fallback) if fallback.is_file() else None


def is_wsl() -> bool:
    """Whether Vibe runs inside WSL and shares the Windows host's power state."""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def _start_macos(mode: SleepPreventionMode) -> PowerAssertion | None:
    executable = shutil.which("caffeinate") or "/usr/bin/caffeinate"
    arguments = [executable, "-i"]
    if mode in _DISPLAY_MODES:
        arguments.append("-d")
    if mode is SleepPreventionMode.SYSTEM:
        arguments.append("-s")
    # ``-w`` ties caffeinate to this process: it exits if Vibe is killed.
    arguments.extend(["-w", str(os.getpid())])
    try:
        process = subprocess.Popen(
            arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError as exc:
        logger.debug("Unable to start caffeinate: %s", exc)
        return None
    return _ProcessAssertion(process)


def _start_linux(mode: SleepPreventionMode) -> PowerAssertion | None:
    assertions: list[PowerAssertion] = []
    login1 = _Login1Assertion.start(_LINUX_INHIBIT_WHAT[mode])
    if login1 is not None:
        assertions.append(login1)
    if mode in _DISPLAY_MODES:
        screensaver = _ScreenSaverAssertion.start()
        if screensaver is not None:
            assertions.append(screensaver)
    if not assertions:
        return None
    return _CompositeAssertion(assertions)


def start_power_assertion(mode: SleepPreventionMode) -> PowerAssertion | None:
    """Acquire the strongest assertion ``mode`` asks for, or None if unavailable."""
    if mode is SleepPreventionMode.OFF:
        return None
    if sys.platform == "darwin":
        return _start_macos(mode)
    if sys.platform == "win32":
        return _WindowsAssertion.start(mode)
    if sys.platform == "linux":
        if is_wsl():
            wsl = _WslAssertion.start(mode)
            if wsl is not None:
                return wsl
        return _start_linux(mode)
    return None


@dataclass(frozen=True, slots=True)
class _Command:
    owner: str
    active: bool
    mode: SleepPreventionMode


def _strongest_mode(owners: Mapping[str, SleepPreventionMode]) -> SleepPreventionMode:
    return max(
        owners.values(), key=_MODE_STRENGTH.__getitem__, default=SleepPreventionMode.OFF
    )


class SleepPreventer:
    """A process-wide assertion shared by every active session.

    ``set_active`` is cheap and non-blocking: a worker thread coalesces
    commands and acquires or releases the host assertion. An owner is a session
    id, so a subagent's turn keeps the machine awake even when the parent is
    waiting on it.
    """

    def __init__(
        self,
        starter: Callable[[SleepPreventionMode], PowerAssertion | None] | None = None,
    ) -> None:
        self._starter = starter or start_power_assertion
        self._commands: queue.SimpleQueue[_Command | None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._closed = False

    def set_active(
        self, owner: str, *, active: bool, mode: SleepPreventionMode
    ) -> None:
        with self._thread_lock:
            if self._closed:
                return
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="vibe-power", daemon=True
                )
                self._thread.start()
        self._commands.put(_Command(owner, active, mode))

    def close(self) -> None:
        with self._thread_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        self._commands.put(None)
        if thread is not None:
            thread.join(timeout=5.0)

    def _run(self) -> None:
        owners: dict[str, SleepPreventionMode] = {}
        assertion: PowerAssertion | None = None
        held_mode = SleepPreventionMode.OFF
        failed_mode: SleepPreventionMode | None = None
        while (command := self._commands.get()) is not None:
            owners = _apply_command(owners, command)
            while True:
                try:
                    queued = self._commands.get_nowait()
                except queue.Empty:
                    break
                if queued is None:
                    _release(assertion)
                    return
                owners = _apply_command(owners, queued)
            desired = _strongest_mode(owners)
            if desired in {held_mode, failed_mode}:
                continue
            _release(assertion)
            assertion = None
            failed_mode = None
            held_mode = SleepPreventionMode.OFF
            if desired is SleepPreventionMode.OFF:
                continue
            try:
                assertion = self._starter(desired)
            except Exception:
                logger.warning(
                    "Failed to acquire sleep prevention (%s)", desired, exc_info=True
                )
                assertion = None
            if assertion is None:
                failed_mode = desired
                logger.warning(
                    "Sleep prevention (%s) is unavailable on this host", desired
                )
                continue
            held_mode = desired
        _release(assertion)


def _apply_command(
    owners: dict[str, SleepPreventionMode], command: _Command
) -> dict[str, SleepPreventionMode]:
    updated = dict(owners)
    if command.active:
        updated[command.owner] = command.mode
    else:
        updated.pop(command.owner, None)
    return updated


def _release(assertion: PowerAssertion | None) -> None:
    if assertion is not None:
        with suppress(Exception):
            assertion.release()


sleep_preventer = SleepPreventer()
