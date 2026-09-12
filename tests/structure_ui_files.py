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
    "ui/sidebar_appkit.py",
    "ui/sidebar_theme.py",
    "ui/sidebar_prefs.py",
    "ui/sidebar_geometry.py",
    "ui/sidebar_panel.py",
    "ui/sidebar_drag.py",
    "ui/sidebar_tray_wiring.py",
    "ui/sidebar_view_model.py",
    "ui/sidebar_widgets.py",
    "ui/sidebar_compact.py",
    "ui/status_menu.py",
    "ui/screenshot_actions.py",
    "ui/screenshot_hotkey.py",
    "ui/speaker_review.py",
    "ui/processing_actions.py",
    "ui/notes_flow.py",
    "ui/stop_reminder.py",
    "ui/notes_mode.py",
    "ui/notification_actions.py",
)
