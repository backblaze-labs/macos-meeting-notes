"""Local transcription source inventory and SDK containment prefixes."""

LOCAL_SDK_PREFIXES = (
    "mlx",
    "mlx_audio",
    "huggingface_hub",
    "transformers",
    "numpy",
    "safetensors",
    "miniaudio",
)

REQUIRED_LOCAL_SOURCE_FILES = (
    "repo/assemblyai_session.py",
    "repo/local_worker_lifetime.py",
    "service/local_transcription.py",
    "service/transcription_attempts.py",
    "service/legacy_transcription.py",
    "service/markdown_fields.py",
    "ui/local_shutdown.py",
    "types/transcription.py",
    "types/local_transcription.py",
    "types/configuration_capabilities.py",
    "types/local_model_preparation.py",
    "config/transcription_resolution.py",
    "repo/local_model_cache.py",
    "repo/local_models.py",
    "repo/local_process.py",
    "repo/local_transcription.py",
    "repo/local_worker.py",
    "repo/native_audio_decoding.py",
    "service/calendar_auth_command.py",
    "service/readiness_transcription.py",
    "service/local_model_preparation.py",
    "ui/transcription_form.py",
    "ui/local_model_panel.py",
    "ui/local_models.py",
    "ui/transcription_actions.py",
)
