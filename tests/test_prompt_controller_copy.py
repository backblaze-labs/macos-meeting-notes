"""User-facing validation copy for Notes customization."""

from meeting_memory.ui.prompt_controller import _validation_message


def test_storage_marker_error_is_translated_to_user_language() -> None:
    message = _validation_message(ValueError("The Notes layout marker must appear exactly once."))

    assert message == "Remove the app-owned separator from Advanced Markdown before saving."
    assert "marker" not in message


def test_missing_generated_fields_has_a_short_recovery_action() -> None:
    message = _validation_message(
        ValueError("The Notes layout is missing required placeholders: {summary}.")
    )

    assert message == "Include {summary}, {decisions}, and {action_items} before saving."
