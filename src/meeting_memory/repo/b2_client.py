"""Backblaze B2 S3-compatible adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from meeting_memory.config.settings import Settings
from meeting_memory.types.meeting import B2UploadResult, MeetingFiles

USER_AGENT_EXTRA = "b2ai-meeting-memory"
DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)
TRANSCRIPT_MARKDOWN = "transcript.md"
RECORDING_AUDIO = "recording.m4a"


@dataclass(frozen=True)
class B2S3Client:
    application_key_id: str
    application_key: str
    endpoint: str
    region: str
    bucket_name: str
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS
    sleeper: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)

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


def _load_boto3():
    import boto3

    return boto3


def _load_botocore_config():
    from botocore.config import Config

    return Config
