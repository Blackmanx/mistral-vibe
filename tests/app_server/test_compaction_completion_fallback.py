from __future__ import annotations

from collections.abc import Sequence

import pytest

from mistralai_vibe_local_harness.protocol import (
    RustCompletionFailedEvent,
    RustCompletionSucceededEvent,
    RustLLMCallAction,
    RustProtocolError,
)
from mistralai_vibe_local_harness.vibe import (
    LocalModelRoute,
    LocalRuntimeAdapterConfig,
    _completion,
)


def _action() -> RustLLMCallAction:
    action = RustLLMCallAction.model_construct(
        action_id="action-1",
        turn_id=None,
        purpose="compaction",
        compaction_id="compact-1",
        attempt=1,
        trigger="automatic",
        request=None,
        iteration=0,
        max_iterations=None,
        model_input=object(),
    )
    return action


@pytest.mark.asyncio
async def test_a_compaction_retries_the_next_fallback_on_context_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def once(
        action: RustLLMCallAction,
        messages: Sequence[object],
        tools: Sequence[object],
        config: LocalRuntimeAdapterConfig,
        **_: object,
    ) -> RustCompletionSucceededEvent | RustCompletionFailedEvent:
        assert _["route_override"] is not None
        seen.append(_.get("route_override").model)  # type: ignore[union-attr]
        if len(seen) == 1:
            return RustCompletionFailedEvent(
                action_id=action.action_id,
                error=RustProtocolError(
                    code="context_length_exceeded",
                    message="prompt is too long for this model",
                    retryable=False,
                ),
            )
        return RustCompletionSucceededEvent.model_construct(
            action_id=action.action_id, result=object()
        )

    monkeypatch.setattr(_completion, "_execute_completion_once", once)
    config = LocalRuntimeAdapterConfig(
        compaction_model=LocalModelRoute(model="small"),
        compaction_fallback_models=(
            LocalModelRoute(model="large"),
            LocalModelRoute(model="glm"),
        ),
    )

    result = await _completion.execute_completion(_action(), [], [], config)

    assert isinstance(result, RustCompletionSucceededEvent)
    assert seen == ["small", "large"]


@pytest.mark.asyncio
async def test_a_non_overflow_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def once(
        action: RustLLMCallAction,
        messages: Sequence[object],
        tools: Sequence[object],
        config: LocalRuntimeAdapterConfig,
        **_: object,
    ) -> RustCompletionFailedEvent:
        seen.append(_.get("route_override").model)  # type: ignore[union-attr]
        return RustCompletionFailedEvent(
            action_id=action.action_id,
            error=RustProtocolError(
                code="unauthorized", message="bad api key", retryable=False
            ),
        )

    monkeypatch.setattr(_completion, "_execute_completion_once", once)
    config = LocalRuntimeAdapterConfig(
        compaction_model=LocalModelRoute(model="small"),
        compaction_fallback_models=(LocalModelRoute(model="large"),),
    )

    result = await _completion.execute_completion(_action(), [], [], config)

    assert isinstance(result, RustCompletionFailedEvent)
    assert seen == ["small"]
