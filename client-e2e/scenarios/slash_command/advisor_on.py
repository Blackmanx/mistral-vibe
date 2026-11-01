"""`/advisor on` enables the advisor for this session and reports the state."""

from __future__ import annotations

from e2e.app_server.scenario import Timeline

timeline: Timeline = ["/advisor on\r"]

handshake = {
    "session/advisor/state": {
        "enabled": True,
        "fromConfig": False,
    }
}
request_methods = {"session/advisor/state"}

capture_startup = False
screen_contains = ("Advisor on for this session.",)
