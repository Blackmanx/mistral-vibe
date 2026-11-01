"""`/memory` shows the project's remembered facts, lessons, and rules."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

timeline: Timeline = ["/memory\r"]

handshake = {
    "session/memory/read": {
        "text": (
            "Project memory: 2 fact(s), 1 lesson(s), 1 response rule(s).\n"
            "\n"
            "## Facts\n"
            "- [a1b2c3] Deploys need SUDO_ASKPASS set — deploy\n"
            "- [d4e5f6] Unit tests live in tests/unit\n"
            "\n"
            "## Lessons\n"
            "- Always run uv run pytest.\n"
            "\n"
            "## Response rules\n"
            "- no-box-leak\n"
        ),
        "facts": 2,
        "lessons": 1,
        "memoryPath": "/repo/.vibe/memory/MEMORY.md",
        "rulesPath": "/repo/.vibe/response-rules.toml",
        "rules": 1,
    }
}
request_methods = {"session/memory/read"}

capture_startup = False
screen_contains = ("Project memory: 2 fact(s)", "no-box-leak")
