"""`/goal stop` pauses the running goal and points at the resume path."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

timeline: Timeline = ["/goal stop\r"]

handshake = {
    "session/goal/pause": {
        "goal": {
            "id": "goal-1",
            "objective": "Ship the port",
            "status": "paused",
            "tokenBudget": None,
            "tokensUsed": 40,
            "createdAt": 1,
            "updatedAt": 2,
        }
    }
}
request_methods = {"session/goal/pause"}

capture_startup = False
screen_contains = ("Goal stopped.",)
