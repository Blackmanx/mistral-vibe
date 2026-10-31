"""A bare `/goal` reads the paused goal, then resumes it without extra typing."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

timeline: Timeline = ["/goal\r"]

handshake = {
    "session/goal/read": {
        "goal": {
            "id": "goal-1",
            "objective": "Ship the port",
            "status": "paused",
            "tokenBudget": None,
            "tokensUsed": 40,
            "createdAt": 1,
            "updatedAt": 2,
        },
        "continuationRounds": 3,
    },
    "session/goal/resume": {
        "goal": {
            "id": "goal-1",
            "objective": "Ship the port",
            "status": "active",
            "tokenBudget": None,
            "tokensUsed": 40,
            "createdAt": 1,
            "updatedAt": 3,
        }
    },
}
request_methods = {"session/goal/read", "session/goal/resume"}

capture_startup = False
screen_contains = ("Goal resumed.",)
