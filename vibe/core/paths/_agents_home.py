from __future__ import annotations

import os
from pathlib import Path

from vibe.core.paths._vibe_home import GlobalPath

_DEFAULT_AGENTS_HOME = Path.home() / ".agents"


def _get_agents_home() -> Path:
    # ``VIBE_AGENTS_HOME`` relocates the shared agent directory, the way
    # ``VIBE_HOME`` relocates Vibe's own: a test hermeticity switch first, and
    # a way to keep skills and agents on a different mount second.
    override = os.environ.get("VIBE_AGENTS_HOME")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_AGENTS_HOME


AGENTS_HOME = GlobalPath(_get_agents_home)
