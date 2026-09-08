"""UI source inventory used by the mechanical structure gate.

Extracted from `test_structure.py` for the same reason `structure_d2_files.py`
and `structure_native_files.py` were: keeping that file under the 300-line
limit it enforces on everything else.
"""

REQUIRED_UI_SOURCE_FILES = (
    "ui/__init__.py",
    "ui/tray.py",
    "ui/menu.py",
    "ui/audio_modes.py",
    "ui/notes_prompt.py",
    "ui/processing_launch.py",
    "ui/legacy_processing.py",
    "ui/recovery_actions.py",
    "ui/runtime_events.py",
    "ui/setup_readiness.py",
    "ui/runtime_app.py",
    "ui/recording_health.py",
    "ui/recording_duration_guard.py",
    "ui/recording_transitions.py",
    "ui/submenus.py",
    "ui/preferences.py",
    "ui/preference_forms.py",
    "ui/screenshot_actions.py",
    "ui/screenshot_hotkey.py",
)
