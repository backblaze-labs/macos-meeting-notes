"""Runtime boundary from a closed indexed capture to one local meeting."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from meeting_memory.service.meeting_store import MeetingStore
from meeting_memory.service.recovery_audio import RecoveryAudioConverter, RecoveryM4AValidator
from meeting_memory.service.recovery_cleanup import cleanup_recovery_after_commit
from meeting_memory.service.recovery_commit import (
    RecoveryCommitCleanupUncertain,
    RecoveryCommitDurabilityUncertain,
    RecoveryCommitResult,
    commit_recovery,
)
from meeting_memory.service.recovery_index import (
    pin_recovery_source,
    update_recovery_session_meta,
)
from meeting_memory.service.recovery_journal import (
    clear_recovery_binding,
    load_recovery_binding,
    prepare_recovery_binding,
)
from meeting_memory.service.recovery_marker import write_recovery_marker
from meeting_memory.service.recovery_quarantine import quarantine_recovery_publication
from meeting_memory.service.recovery_reconcile import (
    reconcile_uncertain_publication,
)
from meeting_memory.types.events import (
    RecordingCleanupPending,
    RecordingCommitted,
    RecordingPublicationUncertain,
)
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta, MeetingRef, PostCommitPolicy
from meeting_memory.types.recovery import RecoveryIndexEntry, RecoveryOrigin

LOGGER = logging.getLogger(__name__)
EventSink = Callable[[object], None]
PolicyProvider = Callable[[], PostCommitPolicy]
PostCommitLauncher = Callable[[MeetingFiles, PostCommitPolicy], None]


@dataclass(frozen=True)
class LocalRecordingCommitter:
    """Publish local first value before starting any optional work."""

    store: MeetingStore
    event_sink: EventSink
    converter: RecoveryAudioConverter
    validate_m4a: RecoveryM4AValidator
    policy_provider: PolicyProvider = PostCommitPolicy
    post_commit_launcher: PostCommitLauncher | None = None

    def commit(self, entry: RecoveryIndexEntry, meta: MeetingMeta) -> MeetingFiles | None:
        """Commit, verify cleanup, queue success, then launch optional work."""

        binding = load_recovery_binding(self.store.meetings_dir, entry)
        current = binding.entry if binding is not None else entry
        current = (
            update_recovery_session_meta(current, meta)
            if current.origin is RecoveryOrigin.APP_STAGING and current.publication is None
            else current
        )
        if current.meta != meta:
            raise ValueError("legacy recovery metadata cannot be changed during commit")
        current = _pinned_or_pin(current)
        policy = binding.policy if binding is not None else self.policy_provider()
        if binding is None:
            binding = prepare_recovery_binding(self.store.meetings_dir, current, policy)
            current = binding.entry
        if current.publication is not None:
            result = reconcile_uncertain_publication(self.store.meetings_dir, current)
        else:
            try:
                result = commit_recovery(
                    self.store,
                    current,
                    policy,
                    converter=self.converter,
                    validate_m4a=self.validate_m4a,
                    prepare_publication=lambda stage, final_meta: write_recovery_marker(
                        stage,
                        final_meta,
                        binding.token,
                    ),
                    reject_publication=lambda destination: quarantine_recovery_publication(
                        self.store.meetings_dir,
                        destination,
                        binding.token,
                    ),
                )
            except RecoveryCommitCleanupUncertain as exc:
                result = exc.result
            except RecoveryCommitDurabilityUncertain as exc:
                LOGGER.warning("Meeting publication durability is uncertain")
                self.event_sink(RecordingPublicationUncertain(_meeting_ref(exc.result)))
                return None

        binding = load_recovery_binding(self.store.meetings_dir, current)
        if binding is None or binding.entry.publication is None:
            LOGGER.error("Published recovery binding could not be reconciled")
            self.event_sink(RecordingCleanupPending(_meeting_ref(result)))
            return None
        if not self._cleanup(result):
            self.event_sink(RecordingCleanupPending(_meeting_ref(result)))
            return None
        try:
            clear_recovery_binding(self.store.meetings_dir, binding)
        except Exception:
            LOGGER.exception("Cleaned recovery left an inert journal binding")
        self.event_sink(RecordingCommitted(_meeting_ref(result)))
        if self.post_commit_launcher is not None:
            self.post_commit_launcher(result.files, policy)
        return result.files

    @staticmethod
    def _cleanup(result: RecoveryCommitResult) -> bool:
        try:
            cleanup_recovery_after_commit(result.receipt)
        except Exception:
            LOGGER.exception("Committed recording source could not be cleaned up")
            return False
        return True


def _meeting_ref(result: RecoveryCommitResult) -> MeetingRef:
    files = result.files
    return MeetingRef(files.meta.slug, files.meta.calendar_title, files.directory)


def _pinned_or_pin(entry: RecoveryIndexEntry) -> RecoveryIndexEntry:
    provenance = (
        entry.source_device,
        entry.source_inode,
        entry.source_size,
        entry.source_sha256,
    )
    if all(value is not None for value in provenance):
        return entry
    if any(value is not None for value in provenance):
        raise ValueError("recovery source provenance is incomplete")
    return pin_recovery_source(entry)
