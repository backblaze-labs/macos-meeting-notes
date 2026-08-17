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
NOTES_REPORT_TEMPLATE_MARKER = "<!-- meeting-memory:notes-layout -->"
NOTES_PROFILE_MARKER = "<!-- meeting-memory:notes-profile -->"
DEFAULT_NOTES_INSTRUCTIONS_TEMPLATE = """Privacy rules:
- Omit personal information that is not needed to understand the work.
- Do not include emails, phone numbers, addresses, account IDs, or personal anecdotes.
- Prefer speaker labels, roles, or null instead of full names when an owner is uncertain.
- Do not quote casual/private conversation unless it directly affects a work decision.

Content rules:
- Keep generated notes focused on relevant work topics, progress, risks, and next steps.
- Do not infer due dates.
- Preserve technical names, project names, and company/product names when relevant.
"""
DEFAULT_NOTES_REPORT_TEMPLATE = """# Meeting Notes

**Source:** {source_transcript}

## Summary

{summary}

## Decisions

{decisions}

## Action Items

{action_items}
"""
DEFAULT_SUMMARY_PROMPT_TEMPLATE = (
    f"{DEFAULT_NOTES_INSTRUCTIONS_TEMPLATE.rstrip()}\n\n"
    f"{NOTES_REPORT_TEMPLATE_MARKER}\n"
    f"{DEFAULT_NOTES_REPORT_TEMPLATE}"
)
DEFAULT_GOOGLE_CALENDAR_CREDENTIALS_FILE = "credentials.json"
DEFAULT_GOOGLE_CALENDAR_ID = "all"
DEFAULT_KNOWN_SPEAKERS: tuple[KnownSpeaker, ...] = ()
DEFAULT_MEETINGS_DIR = "~/Meetings"
DEFAULT_NOTIFY_MINUTES_BEFORE = 5
DEFAULT_MAX_RECORDING_MINUTES = 180
DEFAULT_CALENDAR_POLL_INTERVAL = 120
