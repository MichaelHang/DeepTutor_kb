"""Fallback window heuristics for un-annotated model names."""

from __future__ import annotations

from deeptutor.services.llm.context_window import (
    DEFAULT_CONTEXT_WINDOW_FALLBACK,
    LARGE_CONTEXT_MODEL_DEFAULT,
    MAX_EFFECTIVE_CONTEXT_WINDOW,
    known_context_window,
    looks_like_large_context_model,
    resolve_effective_context_window,
)


def test_grok_is_treated_as_a_large_context_family() -> None:
    """Un-annotated grok names must not fall back to the 16k default.

    The agentic loop's context-window guard snips every tool result once the
    estimated history exceeds 90% of the resolved window. A 16k guess on a
    128k+ Grok model therefore empties every tool payload and the model
    re-calls the same tool forever.
    """
    assert looks_like_large_context_model("grok-4.6") is True
    assert looks_like_large_context_model("grok-4") is True
    window = resolve_effective_context_window(model="grok-4.6")
    assert window == LARGE_CONTEXT_MODEL_DEFAULT
    assert window > DEFAULT_CONTEXT_WINDOW_FALLBACK


def test_unknown_model_still_uses_the_small_fallback() -> None:
    assert looks_like_large_context_model("mystery-7b") is False
    assert resolve_effective_context_window(model="mystery-7b") == (DEFAULT_CONTEXT_WINDOW_FALLBACK)


def test_explicit_catalog_window_wins_over_the_family_heuristic() -> None:
    assert resolve_effective_context_window(context_window=500_000, model="grok-4.6") == 500_000


def test_mimo_ids_use_their_known_window_not_the_small_fallback() -> None:
    """Xiaomi MiMo ships a 1M-token window on every published id.

    The models.dev snapshot the table was built from (2026-09-17) predates
    MiMo, so ``mimo-v2.6-pro`` missed the table entirely and fell back to
    16_384. That number is not cosmetic: the agentic loop compresses history
    at 35% of it (5.7k tokens) and the request guard snips every tool result
    at 90% (14.7k) — on a model that can hold a million tokens.
    """
    for model in (
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "mimo-v2.5-pro-ultraspeed",
        "mimo-v2.6-flash",
        "mimo-v2.6-pro",
        "mimo-v2.6-pro-ultraspeed",
    ):
        assert known_context_window(model) == MAX_EFFECTIVE_CONTEXT_WINDOW, model
        assert resolve_effective_context_window(model=model) == MAX_EFFECTIVE_CONTEXT_WINDOW, model


def test_mimo_family_marker_covers_ids_missing_from_the_table() -> None:
    """A newer MiMo id without its own table entry must not fall to 16k."""
    assert looks_like_large_context_model("mimo-v2.7") is True
    assert resolve_effective_context_window(model="mimo-v2.7") == LARGE_CONTEXT_MODEL_DEFAULT
    assert LARGE_CONTEXT_MODEL_DEFAULT > DEFAULT_CONTEXT_WINDOW_FALLBACK
