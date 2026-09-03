"""Documented provider output limits for configured Claude models."""

from __future__ import annotations

MODEL_OUTPUT_TOKEN_CAPS = {
    "claude-3-5-": 8_192,
    "claude-3-opus": 4_096,
    "claude-3-haiku": 4_096,
    "claude-3-sonnet": 4_096,
}


def model_output_tokens(model: str, ceiling: int) -> int:
    """Clamp a shared ceiling to the configured model's documented output limit."""

    name = str(model).strip().lower()
    caps = [cap for prefix, cap in MODEL_OUTPUT_TOKEN_CAPS.items() if name.startswith(prefix)]
    return min([ceiling, *caps])
