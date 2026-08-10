"""Capability-aware preflight output for Meeting Memory."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from meeting_memory.service.readiness import load_readiness_report
from meeting_memory.types.capabilities import ReadinessReport


def run_checks() -> ReadinessReport:
    """Return the same typed report consumed by the in-app setup check."""

    return load_readiness_report()


def render_results(report: ReadinessReport) -> str:
    """Render every capability in stable product order."""

    lines: list[str] = []
    for status in report.statuses:
        lines.append(
            f"[{status.state.value.upper()}] {status.capability.label}: {status.summary}"
        )
        if status.action:
            lines.append(f"      action: {status.action}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    report = run_checks()
    sys.stdout.write(render_results(report))
    return 0 if report.recording_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
