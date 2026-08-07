"""Command-line entrypoint for meeting-memory."""

from __future__ import annotations

import argparse
import queue
import sys
from collections.abc import Sequence
from pathlib import Path

from meeting_memory import __version__
from meeting_memory.doctor import main as doctor_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meeting-memory")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("setup", help="prepare first-run local setup")
    subcommands.add_parser("doctor", help="run preflight checks")
    subcommands.add_parser("build-native-audio", help="build the macOS audio helper")
    subcommands.add_parser("auth", help="run Google Calendar OAuth setup")
    subcommands.add_parser("install-macos-app", help="install the clickable macOS app")
    subcommands.add_parser("reload-macos-app", help="install, quit, and reopen the macOS app")
    subcommands.add_parser("open-macos-app", help="open the installed macOS app")
    subcommands.add_parser("quit-macos-app", help="quit the installed macOS app")
    subcommands.add_parser("install-launch-agent", help="start at login in the background")
    subcommands.add_parser("uninstall-launch-agent", help="remove the login LaunchAgent")
    search_parser = subcommands.add_parser("search", help="search local meeting markdown")
    search_parser.add_argument("query", nargs="+", help="terms to search for")
    search_parser.add_argument("--limit", type=int, default=10, help="maximum results to show")
    relabel_parser = subcommands.add_parser("relabel", help="apply transcript speaker aliases")
    relabel_parser.add_argument("path", type=Path, help="meeting folder or transcript.md path")
    summarize_parser = subcommands.add_parser(
        "summarize",
        help="generate notes.md from reviewed transcript.md",
    )
    summarize_parser.add_argument("path", type=Path, help="meeting folder or transcript.md path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "setup":
        return run_setup()
    if args.command == "doctor":
        return doctor_main(())
    if args.command == "build-native-audio":
        from meeting_memory.service.native_audio_setup import build_native_audio

        return build_native_audio(_project_dir())
    if args.command == "auth":
        return run_auth()
    if args.command == "install-macos-app":
        return install_macos_app()
    if args.command == "reload-macos-app":
        return reload_macos_app()
    if args.command == "open-macos-app":
        return open_macos_app()
    if args.command == "quit-macos-app":
        return quit_macos_app()
    if args.command == "install-launch-agent":
        return install_launch_agent()
    if args.command == "uninstall-launch-agent":
        return uninstall_launch_agent()
    if args.command == "search":
        return run_search(" ".join(args.query), limit=args.limit)
    if args.command == "relabel":
        return run_relabel(args.path)
    if args.command == "summarize":
        return run_summarize(args.path)

    return run_app()


def run_auth() -> int:
    from pydantic import ValidationError

    from meeting_memory.config.settings import format_settings_error, load_google_auth_settings
    from meeting_memory.repo.calendar_client import GoogleCalendarClient

    try:
        settings = load_google_auth_settings()
    except ValidationError as exc:
        sys.stderr.write(format_settings_error(exc))
        return 2

    credentials_path = _resolve_project_path(settings.google_credentials_path)
    if not credentials_path.exists():
        sys.stderr.write(f"Google OAuth credentials file is missing: {credentials_path}\n")
        sys.stderr.write("Download Desktop app credentials and update .env if needed.\n")
        return 2

    GoogleCalendarClient(
        credentials_file=credentials_path,
        calendar_id=settings.google_calendar_id,
        known_speakers=settings.known_speakers,
    ).authenticate()
    sys.stderr.write("Google Calendar auth token saved to Keychain.\n")
    return 0


def run_setup() -> int:
    from meeting_memory.doctor import render_results, run_checks
    from meeting_memory.service.macos_app import install_macos_app as install
    from meeting_memory.service.setup import setup_actions

    project_dir = _project_dir()
    for action in setup_actions(project_dir):
        status = "created" if action.changed else "ok"
        sys.stdout.write(f"[{status}] {action.name}: {action.message}\n")

    app_path = install(project_dir=project_dir)
    sys.stdout.write(f"[ok] macos-app: installed {app_path}\n\n")

    results = run_checks()
    sys.stdout.write(render_results(results))
    failures = [result for result in results if not result.ok and not result.warning]
    if failures:
        sys.stdout.write("\nNext steps:\n")
        for result in failures:
            if result.fix:
                sys.stdout.write(f"- {result.name}: {result.fix}\n")
        sys.stdout.write("\nB2 remains required before Meeting Memory is ready to record.\n")
        return 0

    sys.stdout.write("\nSetup checks passed. Open Meeting Memory from Spotlight or Finder.\n")
    return 0


def install_launch_agent() -> int:
    from meeting_memory.service.launch_agent import install_launch_agent as install

    plist_path = install(project_dir=_project_dir())
    sys.stderr.write(f"LaunchAgent installed: {plist_path}\n")
    return 0


def install_macos_app() -> int:
    from meeting_memory.service.macos_app import install_macos_app as install

    app_path = install(project_dir=_project_dir())
    sys.stderr.write(f"macOS app installed: {app_path}\n")
    return 0


def reload_macos_app() -> int:
    from meeting_memory.service.macos_app import reload_macos_app as reload_app

    app_path = reload_app(project_dir=_project_dir())
    sys.stderr.write(f"macOS app reloaded: {app_path}\n")
    return 0


def open_macos_app() -> int:
    from meeting_memory.service.macos_app import open_macos_app as open_app

    open_app()
    return 0


def quit_macos_app() -> int:
    from meeting_memory.service.macos_app import quit_macos_app as quit_app

    quit_app()
    return 0


def uninstall_launch_agent() -> int:
    from meeting_memory.service.launch_agent import uninstall_launch_agent as uninstall

    plist_path = uninstall()
    sys.stderr.write(f"LaunchAgent removed: {plist_path}\n")
    return 0


def run_search(query: str, *, limit: int) -> int:
    from meeting_memory.config.settings import validate_or_exit
    from meeting_memory.service.search import search_meetings

    settings = validate_or_exit()
    results = search_meetings(settings.meetings_dir_path, query, limit=limit)
    if not results:
        sys.stdout.write("No matching meetings found.\n")
        return 1

    for result in results:
        sys.stdout.write(
            f"{result.started_at:%Y-%m-%d %H:%M} · {result.title}\n"
            f"  {result.path}\n"
            f"  {result.excerpt}\n"
        )
    return 0


def run_relabel(path: Path) -> int:
    from meeting_memory.service.transcript_review import relabel_transcript

    transcript_path = relabel_transcript(path)
    sys.stderr.write(f"Transcript relabeled: {transcript_path}\n")
    return 0


def run_summarize(path: Path) -> int:
    from meeting_memory.config.settings import validate_or_exit
    from meeting_memory.repo.summarizer import ClaudeSummarizer
    from meeting_memory.service.transcript_review import generate_notes_from_transcript

    settings = validate_or_exit()
    notes_path = generate_notes_from_transcript(path, ClaudeSummarizer.from_settings(settings))
    sys.stderr.write(f"Notes written: {notes_path}\n")
    return 0


def run_app() -> int:
    from pydantic import ValidationError

    from meeting_memory.config.settings import format_settings_error, load_settings
    from meeting_memory.doctor import run_checks
    from meeting_memory.logging_config import configure_logging
    from meeting_memory.repo.b2_client import B2S3Client
    from meeting_memory.repo.calendar_client import GoogleCalendarClient
    from meeting_memory.repo.summarizer import ClaudeSummarizer
    from meeting_memory.repo.transcription import AssemblyAITranscriptionClient
    from meeting_memory.service.calendar_watcher import CalendarWatcher
    from meeting_memory.service.pipeline import Pipeline
    from meeting_memory.service.processing_retry import retry_failed_processing
    from meeting_memory.service.recorder import RecorderService
    from meeting_memory.service.recording_context import current_recording_context
    from meeting_memory.service.sync import sync_pending_meetings
    from meeting_memory.ui.tray import RumpsTrayApp, TrayController

    try:
        settings = load_settings()
    except ValidationError as exc:
        sys.stderr.write(format_settings_error(exc))
        return run_setup_required_app()

    configure_logging()
    event_queue: queue.Queue[object] = queue.Queue()
    b2_client = B2S3Client.from_settings(settings)
    calendar_client = GoogleCalendarClient.from_settings(settings)
    pipeline = Pipeline(
        meetings_dir=settings.meetings_dir_path,
        transcription_client=AssemblyAITranscriptionClient.from_settings(settings),
        summarizer_client=ClaudeSummarizer.from_settings(settings),
        b2_client=b2_client,
        event_sink=event_queue.put,
    )
    recorder = RecorderService()
    controller = TrayController(
        settings=settings,
        recorder=recorder,
        pipeline=pipeline,
        event_queue=event_queue,
        sync_runner=lambda: sync_pending_meetings(settings.meetings_dir_path, b2_client),
        processing_retry_runner=lambda: retry_failed_processing(
            settings.meetings_dir_path,
            pipeline,
        ),
        recording_context_provider=lambda: current_recording_context(
            calendar_client,
            now=recorder.now(),
        ),
    )
    watcher = CalendarWatcher(
        client=calendar_client,
        event_sink=event_queue.put,
        notify_minutes_before=settings.notify_minutes_before,
        poll_interval_seconds=settings.calendar_poll_interval,
    )
    watcher.start()
    RumpsTrayApp(controller, doctor_results=run_checks()).run()
    return 0


def run_setup_required_app() -> int:
    from meeting_memory.doctor import run_checks
    from meeting_memory.logging_config import configure_logging
    from meeting_memory.ui.setup_tray import RumpsSetupApp

    configure_logging()
    RumpsSetupApp(doctor_results=run_checks()).run()
    return 0


def _project_dir() -> Path:
    source_root = Path(__file__).resolve().parents[2]
    return source_root if (source_root / "src" / "meeting_memory").exists() else Path.cwd()


def _resolve_project_path(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else _project_dir() / expanded


if __name__ == "__main__":
    raise SystemExit(main())
