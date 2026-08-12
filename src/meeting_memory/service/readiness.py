"""Capability-scoped, local-first readiness diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.service.configuration_loader import (
    LoadedConfiguration,
    load_configuration,
)
from meeting_memory.service.configuration_sources import PreferenceReader, SecretReader
from meeting_memory.service.readiness_configuration import annotate_process_environment
from meeting_memory.service.readiness_integrations import TokenReader, optional_statuses
from meeting_memory.service.recorder import DEFAULT_CAPTURE_MODE
from meeting_memory.service.recording_readiness import (
    DurableProbe,
    NativeProbe,
    recording_core_status,
)
from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)
from meeting_memory.types.configuration_resolution import ConfigurationUse


def load_readiness_report(
    env_file: str | Path | None = ".env",
    *,
    process_environment: Mapping[str, str] | None = None,
    preference_reader: PreferenceReader | None = None,
    secret_reader: SecretReader | None = None,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
) -> ReadinessReport:
    """Load the shared effective snapshot and always return a complete report."""

    try:
        configuration = load_configuration(
            ConfigurationUse.READINESS,
            env_file=env_file,
            process_environment=process_environment,
            preference_reader=preference_reader,
            secret_reader=secret_reader,
        )
    except Exception:
        return _configuration_failure_report()
    return build_readiness_report(
        configuration.settings,
        configuration=configuration,
        capture_mode=capture_mode,
    )


def build_readiness_report(
    settings: RuntimeSettings,
    *,
    native_probe: NativeProbe | None = None,
    token_reader: TokenReader | None = None,
    durable_probe: DurableProbe | None = None,
    system_name: str | None = None,
    kernel_release: str | None = None,
    python_version: tuple[int, int] | None = None,
    configuration: LoadedConfiguration | None = None,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
) -> ReadinessReport:
    """Check local readiness without contacting an optional provider."""

    try:
        core = recording_core_status(
            settings,
            native_probe=native_probe,
            durable_probe=durable_probe,
            system_name=system_name,
            kernel_release=kernel_release,
            python_version=python_version,
            capture_mode=capture_mode,
        )
        core = annotate_process_environment(core, configuration)
        statuses = (
            core,
            *optional_statuses(
                settings,
                token_reader=token_reader,
                configuration=configuration,
            ),
        )
        return ReadinessReport(statuses)
    except Exception:
        return failed_readiness_report()


def checking_readiness_report() -> ReadinessReport:
    """Return the non-blocking transient report rendered during an explicit check."""

    return ReadinessReport(
        tuple(
            CapabilityStatus(capability, CapabilityState.CHECKING, "Readiness check in progress.")
            for capability in Capability
        )
    )


def failed_readiness_report() -> ReadinessReport:
    """Return a sanitized terminal report when the diagnostic itself fails."""

    return ReadinessReport(
        tuple(
            CapabilityStatus(
                capability,
                CapabilityState.FAILED,
                f"{capability.label} readiness could not be determined.",
                "Retry Check Setup & Dependencies.",
            )
            for capability in Capability
        )
    )


def _configuration_failure_report() -> ReadinessReport:
    core = _failed(
        Capability.RECORDING_CORE,
        "Recording Core configuration could not be loaded.",
        "Fix MEETINGS_DIR and MAX_RECORDING_MINUTES, then rerun the setup check.",
    )
    return _report_with_unconfigured_optionals(core)


def _report_with_unconfigured_optionals(core: CapabilityStatus) -> ReadinessReport:
    return ReadinessReport(
        (
            core,
            *(
                _unconfigured(
                    capability,
                    "Readiness is unavailable until local configuration is valid.",
                    "Fix Recording Core configuration, then rerun the setup check.",
                )
                for capability in Capability
                if capability is not Capability.RECORDING_CORE
            ),
        )
    )


def _unconfigured(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.UNCONFIGURED, summary, action)


def _failed(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.FAILED, summary, action)
