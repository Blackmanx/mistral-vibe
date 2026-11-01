"""Backend-contract coverage for goal mode: `/goal` must start working on its own."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib

import httpx
import pytest
import respx

from vibe.app_server._model import validate_wire
from vibe.app_server.models import PublicTurnStatus
from vibe.app_server.protocol import SessionGoalClearResponse, SessionGoalSetResponse
from vibe.app_server.session import AppServerSession


async def _drain_events(session: AppServerSession) -> None:
    async for _ in session.events():
        pass


@pytest.mark.asyncio
async def test_setting_a_goal_kicks_off_a_turn_on_the_live_backend(
    backend_contract_mistral_api: respx.Route,
    backend_contract_mistral_response: Callable[..., httpx.Response],
    backend_contract_session: AppServerSession,
) -> None:
    """`session/goal/set` on a real backend must start a turn by itself.

    The kickoff path is a background task that calls the full ``start_turn``
    pipeline — the unit tests mock ``_start_turn``, so this is the only test
    that catches a wedge anywhere between the goal record and the harness.
    """
    session = backend_contract_session
    backend_contract_mistral_api.mock(
        return_value=backend_contract_mistral_response("worked on the objective")
    )
    client = await session._ensure_attached()

    response = validate_wire(
        SessionGoalSetResponse,
        await client.request(
            "session/goal/set",
            {"sessionId": session.session_id, "objective": "Ship the widget"},
        ),
    )
    assert response.goal.objective == "Ship the widget"

    # Consume the event stream so the session projection keeps up.
    consumer = asyncio.create_task(_drain_events(session))
    try:
        # The kickoff turn is injected, so the objective text never lands in
        # public history; the observable is a turn that runs to completion
        # against the mocked model without any user action.
        completed = False
        for _ in range(150):  # up to ~15s
            await asyncio.sleep(0.1)
            latest = session.state.latest_turn
            if latest is not None and latest.status is PublicTurnStatus.COMPLETED:
                completed = True
                break
        assert completed, (
            "no turn ran to completion after goal/set — the kickoff "
            "never started working"
        )
        assert backend_contract_mistral_api.called, (
            "the kickoff turn never reached the model"
        )
        request_body = backend_contract_mistral_api.calls.last.request.content.decode()
        assert "Ship the widget" in request_body, (
            "the kickoff turn did not carry the objective to the model"
        )
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer
        cleared = validate_wire(
            SessionGoalClearResponse,
            await client.request(
                "session/goal/clear", {"sessionId": session.session_id}
            ),
        )
        assert cleared.cleared
