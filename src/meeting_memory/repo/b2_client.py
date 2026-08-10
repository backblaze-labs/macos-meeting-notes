"""Backblaze B2 S3-compatible adapter."""

from __future__ import annotations

import time
from collections.abc import Callable

from meeting_memory.config.settings import Settings
from meeting_memory.repo.b2_snapshot import open_verified_backup_snapshot
from meeting_memory.types.artifacts import (
    BackupSnapshotUpload,
    BackupSnapshotUploadResult,
    BackupUploadCancellation,
    BackupUploadDisposition,
    LegacyBackupUpload,
)
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles

USER_AGENT_EXTRA = "b2ai-meeting-memory"
DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)
TRANSCRIPT_MARKDOWN = "transcript.md"
RECORDING_AUDIO = "recording.m4a"


class B2S3Client:
    __slots__ = (
        "_application_key_id",
        "_application_key",
        "endpoint",
        "region",
        "bucket_name",
        "retry_delays",
        "sleeper",
    )

    def __init__(
        self,
        application_key_id: str,
        application_key: str,
        endpoint: str,
        region: str,
        bucket_name: str,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        object.__setattr__(self, "_application_key_id", application_key_id)
        object.__setattr__(self, "_application_key", application_key)
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "region", region)
        object.__setattr__(self, "bucket_name", bucket_name)
        object.__setattr__(self, "retry_delays", retry_delays)
        object.__setattr__(self, "sleeper", sleeper)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("backup adapter is immutable")

    @property
    def application_key_id(self) -> str:
        return self._application_key_id

    @property
    def application_key(self) -> str:
        return self._application_key

    def __repr__(self) -> str:
        return "B2S3Client(credentials=<redacted>, destination=<configured>)"

    @classmethod
    def from_settings(cls, settings: Settings) -> B2S3Client:
        return cls(
            application_key_id=settings.b2_application_key_id,
            application_key=settings.b2_application_key,
            endpoint=settings.b2_endpoint,
            region=settings.b2_region,
            bucket_name=settings.b2_bucket_name,
        )

    def upload_meeting(self, files: MeetingFiles) -> B2UploadResult:
        client = self._client()
        audio_paths = (files.audio_path, *files.extra_audio_paths)
        audio_keys = tuple(f"meetings/{files.meta.slug}/{path.name}" for path in audio_paths)
        transcript_key = f"meetings/{files.meta.slug}/{TRANSCRIPT_MARKDOWN}"

        for audio_path, audio_key in zip(audio_paths, audio_keys, strict=True):
            self._upload_file(client, str(audio_path), audio_key)
        self._upload_file(client, str(files.markdown_path), transcript_key)
        return B2UploadResult(
            audio_key=audio_keys[0],
            transcript_key=transcript_key,
            audio_keys=audio_keys,
        )

    def upload_legacy_snapshot(self, request: LegacyBackupUpload) -> B2UploadResult:
        """Upload only private pinned legacy streams under their historical keys."""

        client = self._client()
        audio_keys = tuple(
            f"meetings/{request.meeting_slug}/{item.filename}" for item in request.audio
        )
        transcript_key = f"meetings/{request.meeting_slug}/{TRANSCRIPT_MARKDOWN}"
        for item, key in zip(request.audio, audio_keys, strict=True):
            self._upload_stream(client, item.stream, key)
        self._upload_stream(client, request.transcript.stream, transcript_key)
        return B2UploadResult(audio_keys[0], transcript_key, audio_keys)

    def upload_backup_snapshot(
        self,
        request: BackupSnapshotUpload,
        *,
        cancellation: BackupUploadCancellation,
    ) -> BackupSnapshotUploadResult:
        """Upload at safe boundaries without owning durable meeting state."""

        if cancellation.cancelled:
            return _stopped_upload(request, BackupUploadDisposition.CANCELLED)
        audio_key = f"meetings/{request.meeting_slug}/{RECORDING_AUDIO}"
        transcript_key = f"meetings/{request.meeting_slug}/{TRANSCRIPT_MARKDOWN}"
        with open_verified_backup_snapshot(request) as snapshot:
            if cancellation.cancelled:
                return _stopped_upload(request, BackupUploadDisposition.CANCELLED)
            client = self._client()
            if not self._upload_stream_while_enabled(
                client,
                snapshot.audio,
                audio_key,
                cancellation,
            ):
                return _stopped_upload(request, BackupUploadDisposition.CANCELLED)
            if cancellation.cancelled:
                return _stopped_upload(
                    request,
                    BackupUploadDisposition.PARTIAL,
                    audio_key=audio_key,
                )
            if not self._upload_stream_while_enabled(
                client,
                snapshot.transcript,
                transcript_key,
                cancellation,
            ):
                return _stopped_upload(
                    request,
                    BackupUploadDisposition.PARTIAL,
                    audio_key=audio_key,
                )
        return BackupSnapshotUploadResult(
            disposition=BackupUploadDisposition.COMPLETE,
            meeting_slug=request.meeting_slug,
            revision=request.revision,
            audio_key=audio_key,
            transcript_key=transcript_key,
        )

    def _client(self):
        boto3 = _load_boto3()
        Config = _load_botocore_config()
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.application_key_id,
            aws_secret_access_key=self.application_key,
            config=Config(user_agent_extra=USER_AGENT_EXTRA),
        )

    def _upload_file(self, client, filename: str, key: str) -> None:
        for attempt, delay in enumerate((*self.retry_delays, None)):
            try:
                client.upload_file(filename, self.bucket_name, key)
                return
            except Exception:
                if delay is None:
                    raise
                self.sleeper(delay)

    def _upload_stream(self, client, stream, key: str) -> None:
        for delay in (*self.retry_delays, None):
            try:
                stream.seek(0)
                client.upload_fileobj(stream, self.bucket_name, key)
                return
            except Exception:
                if delay is None:
                    raise
                self.sleeper(delay)

    def _upload_stream_while_enabled(
        self,
        client,
        stream,
        key: str,
        cancellation: BackupUploadCancellation,
    ) -> bool:
        for delay in (*self.retry_delays, None):
            if cancellation.cancelled:
                return False
            try:
                stream.seek(0)
                client.upload_fileobj(stream, self.bucket_name, key)
                return True
            except Exception:
                if delay is None:
                    raise
                if cancellation.cancelled:
                    return False
                self.sleeper(delay)
        return False


def _stopped_upload(
    request: BackupSnapshotUpload,
    disposition: BackupUploadDisposition,
    *,
    audio_key: str | None = None,
) -> BackupSnapshotUploadResult:
    return BackupSnapshotUploadResult(
        disposition=disposition,
        meeting_slug=request.meeting_slug,
        revision=request.revision,
        audio_key=audio_key,
    )


def _load_boto3():
    import boto3

    return boto3


def _load_botocore_config():
    from botocore.config import Config

    return Config
