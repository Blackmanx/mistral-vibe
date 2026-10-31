"""`/goal <objective>` sets the goal without a `set` keyword and reports the pursuit."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

timeline: Timeline = ["/goal Ship the port\r"]

handshake = {
    "session/goal/set": {
        "goal": {
            "id": "goal-1",
            "objective": "Ship the port",
            "status": "active",
            "tokenBudget": None,
            "tokensUsed": 0,
            "createdAt": 1,
            "updatedAt": 1,
        }
    }
}
request_methods = {"session/goal/set"}

capture_startup = False
screen_contains = ("Goal set.",)
