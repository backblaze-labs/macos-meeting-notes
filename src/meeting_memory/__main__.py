"""Command-line entrypoint for meeting-memory."""

from __future__ import annotations

import argparse
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

    sys.stderr.write(
        "Tray application startup is planned for Milestone 4. Run `make doctor` now.\n"
    )
    return 2


def run_auth() -> int:
    from meeting_memory.config.settings import validate_or_exit
    from meeting_memory.repo.calendar_client import GoogleCalendarClient

    settings = validate_or_exit()
    GoogleCalendarClient.from_settings(settings).authenticate()
    sys.stderr.write("Google Calendar auth token saved to Keychain.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
