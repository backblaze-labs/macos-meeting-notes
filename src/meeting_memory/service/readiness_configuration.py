"""Map composed configuration state into optional readiness outcomes."""

from __future__ import annotations

from collections.abc import Callable

from meeting_memory.service.configuration_loader import LoadedConfiguration
from meeting_memory.types.capabilities import Capability, CapabilityState, CapabilityStatus


def effective_optional_status(
    capability: Capability,
    configuration: LoadedConfiguration | None,
    check: Callable[[], CapabilityStatus],
) -> CapabilityStatus:
    """Apply explicit consent and sanitized composition failures to a local check."""

    if configuration is None:
        return safe_optional_status(capability, check)
    resolved = configuration.capability_for(capability)
    issues = tuple(issue for issue in configuration.issues if issue.capability is capability)
    if blocking := next((issue for issue in issues if issue.blocking), None):
        return annotate_process_environment(
            _failed(capability, blocking.summary, blocking.action),
            configuration,
        )
    process_override = configuration.process_environment_active(capability)
    if resolved.preference is False and not process_override:
        return CapabilityStatus(
            capability,
            CapabilityState.UNCONFIGURED,
            f"{capability.label} is disabled; local recording remains available.",
            f"Enable {capability.label} in app configuration to use it for new recordings.",
        )
    if not resolved.enabled and resolved.preference is True:
        return _failed(
            capability,
            f"{capability.label} app-owned configuration is incomplete or invalid.",
            f"Review {capability.label} app configuration, then rerun the setup check.",
        )
    status = safe_optional_status(capability, check)
    if issues and status.state is CapabilityState.READY:
        issue = issues[0]
        status = CapabilityStatus(
            capability,
            CapabilityState.DEGRADED,
            f"{status.summary} {issue.summary}",
            issue.action,
        )
    return annotate_process_environment(status, configuration)


def annotate_process_environment(
    status: CapabilityStatus,
    configuration: LoadedConfiguration | None,
) -> CapabilityStatus:
    """Add value-free provenance when any active field comes from the process."""

    if configuration is None:
        return status
    if configuration.process_environment_active(status.capability):
        note = "Process environment override is active."
    elif configuration.process_environment_selected(status.capability):
        note = "Process environment override requires attention."
    else:
        return status
    if note in status.summary:
        return status
    return CapabilityStatus(
        status.capability,
        status.state,
        f"{status.summary} {note}",
        status.action,
    )


def safe_optional_status(
    capability: Capability,
    check: Callable[[], CapabilityStatus],
) -> CapabilityStatus:
    """Keep a single optional diagnostic failure capability-local and sanitized."""

    try:
        return check()
    except Exception:
        return _failed(
            capability,
            f"{capability.label} readiness could not be determined from local configuration.",
            f"Review {capability.label} settings, then rerun the setup check.",
        )


def _failed(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.FAILED, summary, action)
