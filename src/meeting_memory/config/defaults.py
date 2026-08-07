"""Configuration defaults shared by settings and doctor."""

from meeting_memory.types.speakers import KnownSpeaker

B2_ENV_VARS = (
    "B2_APPLICATION_KEY_ID",
    "B2_APPLICATION_KEY",
    "B2_ENDPOINT",
    "B2_REGION",
    "B2_BUCKET_NAME",
)

ASSEMBLYAI_ENV_VARS = ("ASSEMBLYAI_API_KEY",)

REQUIRED_ENV_VARS = (*B2_ENV_VARS, *ASSEMBLYAI_ENV_VARS)

PLACEHOLDER_MARKERS = ("replace-me", "changeme", "todo", "<", ">")

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"
DEFAULT_SUMMARY_PROMPT_FILE = "prompts/summary.md"
DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE = "credentials.json"
DEFAULT_GOOGLE_CALENDAR_ID = "all"
DEFAULT_KNOWN_SPEAKERS: tuple[KnownSpeaker, ...] = ()
DEFAULT_MEETINGS_DIR = "~/Meetings"
DEFAULT_NOTIFY_MINUTES_BEFORE = 5
DEFAULT_MAX_RECORDING_MINUTES = 180
DEFAULT_CALENDAR_POLL_INTERVAL = 120
