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
    subcommands.add_parser("doctor", help="run preflight checks")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        return doctor_main(())
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

    return run_app()


def run_auth() -> int:
    from meeting_memory.config.settings import validate_or_exit
    from meeting_memory.repo.calendar_client import GoogleCalendarClient

    settings = validate_or_exit()
    GoogleCalendarClient.from_settings(settings).authenticate()
    sys.stderr.write("Google Calendar auth token saved to Keychain.\n")
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


def run_app() -> int:
    from meeting_memory.config.settings import validate_or_exit
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
    from meeting_memory.service.speaker_mapping import load_speaker_mapping
    from meeting_memory.service.sync import sync_pending_meetings
    from meeting_memory.ui.tray import RumpsTrayApp, TrayController

    settings = validate_or_exit()
    configure_logging()
    event_queue: queue.Queue[object] = queue.Queue()
    b2_client = B2S3Client.from_settings(settings)
    calendar_client = GoogleCalendarClient.from_settings(settings)
    speaker_mapping = load_speaker_mapping(settings.speaker_mapping_path)
    pipeline = Pipeline(
        meetings_dir=settings.meetings_dir_path,
        transcription_client=AssemblyAITranscriptionClient.from_settings(settings),
        summarizer_client=ClaudeSummarizer.from_settings(settings),
        b2_client=b2_client,
        event_sink=event_queue.put,
        speaker_mapping=speaker_mapping,
    )
    recorder = RecorderService(audio_device=settings.audio_device)
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


def _project_dir() -> Path:
    source_root = Path(__file__).resolve().parents[2]
    return source_root if (source_root / "src" / "meeting_memory").exists() else Path.cwd()


if __name__ == "__main__":
    raise SystemExit(main())
