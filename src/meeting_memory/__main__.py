"""Command-line entrypoint for meeting-memory."""

from __future__ import annotations

import argparse
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
    subcommands.add_parser(
        "bundle-self-check",
        help="validate a frozen application bundle without external side effects",
    )
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
    if args.command == "bundle-self-check":
        from meeting_memory.service.bundle_self_check import run_bundle_self_check

        return run_bundle_self_check()

    return run_app()


def run_auth() -> int:
    from meeting_memory.repo.calendar_client import GoogleCalendarClient
    from meeting_memory.repo.calendar_oauth import CalendarAuthorizationError
    from meeting_memory.service.configuration_loader import (
        ConfigurationLoadError,
        load_configuration,
    )
    from meeting_memory.types.configuration_resolution import ConfigurationUse

    try:
        loaded = load_configuration(ConfigurationUse.AUTH)
    except ConfigurationLoadError:
        sys.stderr.write("Calendar configuration could not be loaded.\n")
        return 2
    settings = loaded.calendar_auth
    if settings is None:
        sys.stderr.write("Calendar is not configured or is disabled.\n")
        return 2

    try:
        GoogleCalendarClient(
            credentials_file=settings.credentials_file,
            calendar_id=settings.calendar_id,
            known_speakers=settings.known_speakers,
        ).authenticate()
    except CalendarAuthorizationError:
        sys.stderr.write("Google Calendar authorization failed safely.\n")
        sys.stderr.write("Check Calendar setup and try the explicit auth command again.\n")
        return 2

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

    report = run_checks()
    sys.stdout.write(render_results(report))
    if not report.recording_ready:
        from meeting_memory.types.capabilities import Capability

        core = report.status_for(Capability.RECORDING_CORE)
        sys.stdout.write(f"\nRecording Core needs attention: {core.action}\n")
        return 1

    sys.stdout.write(
        "\nRecording Core is usable. Optional capabilities can be configured independently.\n"
    )
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
    from meeting_memory.service.configuration_loader import (
        ConfigurationLoadError,
        load_configuration,
    )
    from meeting_memory.service.search import search_meetings
    from meeting_memory.types.configuration_resolution import ConfigurationUse

    try:
        loaded = load_configuration(ConfigurationUse.SEARCH)
    except ConfigurationLoadError:
        sys.stderr.write("Search configuration could not be loaded.\n")
        return 2
    results = search_meetings(loaded.meetings_dir_path, query, limit=limit)
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
    from meeting_memory.repo.summarizer import ClaudeSummarizer
    from meeting_memory.service.configuration_loader import (
        ConfigurationLoadError,
        load_configuration,
    )
    from meeting_memory.service.runtime_notes import generate_owned_notes
    from meeting_memory.types.configuration_resolution import ConfigurationUse

    try:
        loaded = load_configuration(ConfigurationUse.SUMMARIZE)
    except ConfigurationLoadError:
        sys.stderr.write("Notes configuration could not be loaded.\n")
        return 2
    config = loaded.notes
    if config is None:
        sys.stderr.write("Notes is not configured. Set ANTHROPIC_API_KEY first.\n")
        return 2
    meeting_dir = path.expanduser()
    if not meeting_dir.is_dir():
        meeting_dir = meeting_dir.parent
    try:
        notes_path = generate_owned_notes(
            loaded.meetings_dir_path,
            meeting_dir,
            ClaudeSummarizer(
                api_key=config.api_key,
                model=config.model,
                prompt_file=config.prompt_file,
            ),
        )
    except Exception:
        sys.stderr.write("Notes generation failed safely; the transcript is unchanged.\n")
        return 2
    sys.stderr.write(f"Notes written: {notes_path}\n")
    return 0


def run_app() -> int:
    from meeting_memory.ui.runtime_app import run_runtime_app

    return run_runtime_app()


def run_setup_required_app() -> int:
    from meeting_memory.logging_config import configure_logging
    from meeting_memory.ui.setup_tray import RumpsSetupApp

    configure_logging()
    RumpsSetupApp(readiness_report=None).run()
    return 0


def _project_dir() -> Path:
    from meeting_memory.config.runtime_layout import current_runtime_layout

    root = current_runtime_layout().project_root
    if root is None:
        raise RuntimeError("developer command is unavailable in the bundled app")
    return root


if __name__ == "__main__":
    raise SystemExit(main())
