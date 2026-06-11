"""Command-line entrypoint for meeting-memory."""

from __future__ import annotations

import argparse
import queue
import sys
from collections.abc import Sequence

from meeting_memory import __version__
from meeting_memory.doctor import main as doctor_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meeting-memory")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("doctor", help="run preflight checks")
    subcommands.add_parser("auth", help="run Google Calendar OAuth setup")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        return doctor_main(())
    if args.command == "auth":
        return run_auth()

    return run_app()


def run_auth() -> int:
    from meeting_memory.config.settings import validate_or_exit
    from meeting_memory.repo.calendar_client import GoogleCalendarClient

    settings = validate_or_exit()
    GoogleCalendarClient.from_settings(settings).authenticate()
    sys.stderr.write("Google Calendar auth token saved to Keychain.\n")
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
    from meeting_memory.service.recorder import RecorderService
    from meeting_memory.service.sync import sync_pending_meetings
    from meeting_memory.ui.tray import RumpsTrayApp, TrayController

    settings = validate_or_exit()
    configure_logging()
    event_queue: queue.Queue[object] = queue.Queue()
    b2_client = B2S3Client.from_settings(settings)
    pipeline = Pipeline(
        meetings_dir=settings.meetings_dir_path,
        transcription_client=AssemblyAITranscriptionClient.from_settings(settings),
        summarizer_client=ClaudeSummarizer.from_settings(settings),
        b2_client=b2_client,
        event_sink=event_queue.put,
    )
    recorder = RecorderService(audio_device=settings.audio_device)
    controller = TrayController(
        settings=settings,
        recorder=recorder,
        pipeline=pipeline,
        event_queue=event_queue,
        sync_runner=lambda: sync_pending_meetings(settings.meetings_dir_path, b2_client),
    )
    watcher = CalendarWatcher(
        client=GoogleCalendarClient.from_settings(settings),
        event_sink=event_queue.put,
        notify_minutes_before=settings.notify_minutes_before,
        poll_interval_seconds=settings.calendar_poll_interval,
    )
    watcher.start()
    RumpsTrayApp(controller, doctor_results=run_checks()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
