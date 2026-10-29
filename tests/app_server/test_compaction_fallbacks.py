from __future__ import annotations

from tests.conftest import build_test_vibe_config
from vibe.app_server._runtime import _compaction_fallback_models
from vibe.core.config import ModelConfig


def _models() -> list[ModelConfig]:
    return [
        ModelConfig(name="mistral-small-latest", provider="mistral", alias="small"),
        ModelConfig(name="zai-glm-5-3-flash", provider="mistral", alias="glm-flash"),
        ModelConfig(
            name="mistral-large-latest", provider="mistral", alias="mistral-large"
        ),
        ModelConfig(name="other-large", provider="anthropic", alias="other"),
    ]


def test_auto_order_is_glm_flash_then_large_then_active() -> None:
    config = build_test_vibe_config(
        models=_models(), active_model="small", compaction_model=_models()[0]
    )

    fallbacks = _compaction_fallback_models(
        config,
        config.get_compaction_model(),
        provider="mistral",
        active_model=config.get_active_model(),
    )

    assert [model.alias for model in fallbacks] == ["glm-flash", "mistral-large"]


def test_explicit_aliases_win_and_unknown_or_cross_provider_are_skipped() -> None:
    config = build_test_vibe_config(
        models=_models(),
        active_model="small",
        compaction_model=_models()[0],
        compaction_fallback_models=["mistral-large", "other", "missing"],
    )

    fallbacks = _compaction_fallback_models(
        config,
        config.get_compaction_model(),
        provider="mistral",
        active_model=config.get_active_model(),
    )

    assert [model.alias for model in fallbacks] == ["mistral-large"]


def test_the_primary_model_is_never_a_fallback() -> None:
    config = build_test_vibe_config(
        models=_models(), active_model="glm-flash", compaction_model=_models()[0]
    )

    fallbacks = _compaction_fallback_models(
        config,
        config.get_compaction_model(),
        provider="mistral",
        active_model=config.get_active_model(),
    )

    assert all(model.name != "mistral-small-latest" for model in fallbacks)
