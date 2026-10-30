"""Secondary model calls: ephemeral `/btw`, `consult`, and auto planning.

Nothing here touches the session transcript or exposes tools. Every call is a
one-shot completion, so a failure can never corrupt the main turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from vibe.core.config import (
    ModelConfig,
    ProviderConfig,
    UtilityFeature,
    VibeConfigSchema,
)
from vibe.core.llm.completion import CompletionTransport, complete_once
from vibe.core.llm.utility_completion import select_utility_model
from vibe.core.prompts import UtilityPrompt
from vibe.core.telemetry.build_metadata import build_request_metadata
from vibe.core.types import ImageAttachment, LLMMessage, Role

MAX_TRANSCRIPT_CHARS = 32_000
MAX_ANSWER_TOKENS = 1_200
REQUEST_TIMEOUT_SECONDS = 60.0
RETRY_BUDGET_SECONDS = 20.0


async def answer_side_question(
    *,
    config: VibeConfigSchema,
    transcript: Sequence[str],
    question: str,
    images: Sequence[ImageAttachment] | None = None,
    session_id: str | None = None,
) -> str:
    model, provider = select_utility_model(config, feature=UtilityFeature.BTW)
    if images and not model.supports_images:
        raise ValueError(
            "The model configured for /btw does not accept images; "
            "set [utility_models] btw to a vision-capable model."
        )
    text = _compact_transcript(transcript)
    content = UtilityPrompt.BTW.read().format(transcript=text, question=question)
    return await complete_with_model(
        config=config,
        model=model,
        provider=provider,
        content=content,
        images=images,
        session_id=session_id,
    )


async def complete_with_feature(
    *,
    config: VibeConfigSchema,
    feature: UtilityFeature,
    content: str,
    max_tokens: int = MAX_ANSWER_TOKENS,
    session_id: str | None = None,
    system_prompt: str | None = None,
    images: Sequence[ImageAttachment] | None = None,
) -> str:
    model, provider = select_utility_model(config, feature=feature)
    if images and not model.supports_images:
        raise ValueError(
            f"The model configured for {feature.value} does not accept images; "
            f"set [utility_models] {feature.value} to a vision-capable model."
        )
    return await complete_with_model(
        config=config,
        model=model,
        provider=provider,
        content=content,
        max_tokens=max_tokens,
        session_id=session_id,
        system_prompt=system_prompt,
        images=images,
    )


async def complete_with_model(
    *,
    config: VibeConfigSchema,
    model: ModelConfig,
    provider: ProviderConfig,
    content: str,
    session_id: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = MAX_ANSWER_TOKENS,
    images: Sequence[ImageAttachment] | None = None,
) -> str:
    messages: list[LLMMessage] = []
    if system_prompt:
        messages.append(LLMMessage(role=Role.system, content=system_prompt))
    messages.append(
        LLMMessage(
            role=Role.user, content=content, images=list(images) if images else None
        )
    )
    result = await complete_once(
        provider=provider,
        model=model,
        messages=messages,
        temperature=model.temperature,
        max_tokens=max_tokens,
        metadata=build_request_metadata(
            launch_context=None, session_id=session_id, call_type="secondary_call"
        ).model_dump(exclude_none=True),
        transport=replace(
            CompletionTransport.from_config(config),
            timeout_s=REQUEST_TIMEOUT_SECONDS,
            retry_budget_s=RETRY_BUDGET_SECONDS,
        ),
    )
    return (result.text or "").strip()


def _compact_transcript(lines: Sequence[str]) -> str:
    """Keep the newest context that fits, cutting on a line boundary."""
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        size = len(line) + 1
        if used + size > MAX_TRANSCRIPT_CHARS:
            break
        kept.append(line)
        used += size
    kept.reverse()
    if not kept and lines:
        kept = [lines[-1][-MAX_TRANSCRIPT_CHARS:]]
    if len(kept) < len(lines):
        kept.insert(0, "[earlier conversation omitted]")
    return "\n".join(kept)


__all__ = ["answer_side_question", "complete_with_feature", "complete_with_model"]
