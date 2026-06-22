"""Tests for the Backblaze B2 S3 adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from meeting_memory.config.settings import Settings
from meeting_memory.repo import b2_client
from meeting_memory.repo.b2_client import USER_AGENT_EXTRA, B2S3Client
from meeting_memory.types.meeting import MeetingFiles, MeetingMeta


def test_b2_client_uses_s3_endpoint_user_agent_and_object_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_boto3 = FakeBoto3()
    monkeypatch.setattr(b2_client, "_load_boto3", lambda: fake_boto3)
    monkeypatch.setattr(b2_client, "_load_botocore_config", lambda: FakeConfig)

    client = B2S3Client(
        application_key_id="key-id",
        application_key="secret",
        endpoint="https://s3.us-west-004.backblazeb2.com",
        region="us-west-004",
        bucket_name="bucket",
    )

    result = client.upload_meeting(_files(tmp_path))

    assert result.audio_key == "meetings/2026-06-10_09-00_product-sync/recording.m4a"
    assert result.transcript_key == "meetings/2026-06-10_09-00_product-sync/transcript.md"
    assert fake_boto3.client_kwargs["service_name"] == "s3"
    assert fake_boto3.client_kwargs["endpoint_url"] == "https://s3.us-west-004.backblazeb2.com"
    assert fake_boto3.client_kwargs["config"].user_agent_extra == USER_AGENT_EXTRA
    assert fake_boto3.s3_client.uploads == [
        (
            str(tmp_path / "recording.m4a"),
            "bucket",
            "meetings/2026-06-10_09-00_product-sync/recording.m4a",
        ),
        (
            str(tmp_path / "transcript.md"),
            "bucket",
            "meetings/2026-06-10_09-00_product-sync/transcript.md",
        ),
    ]


def test_b2_client_retries_failed_upload(tmp_path: Path, monkeypatch) -> None:
    fake_boto3 = FakeBoto3(failures_before_success=1)
    sleeps: list[float] = []
    monkeypatch.setattr(b2_client, "_load_boto3", lambda: fake_boto3)
    monkeypatch.setattr(b2_client, "_load_botocore_config", lambda: FakeConfig)

    client = B2S3Client(
        application_key_id="key-id",
        application_key="secret",
        endpoint="https://s3.example.com",
        region="us-west-004",
        bucket_name="bucket",
        retry_delays=(2.0,),
        sleeper=sleeps.append,
    )

    client.upload_meeting(_files(tmp_path))

    assert sleeps == [2.0]
    assert fake_boto3.s3_client.attempts == 3


def test_b2_client_from_settings_uses_required_env_names() -> None:
    settings = Settings(
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
    )

    client = B2S3Client.from_settings(settings)

    assert client.application_key_id == "key-id"
    assert client.application_key == "secret"
    assert client.endpoint == "https://s3.example.com"
    assert client.region == "us-west-004"
    assert client.bucket_name == "bucket"


class FakeConfig:
    def __init__(self, *, user_agent_extra: str):
        self.user_agent_extra = user_agent_extra


@dataclass
class FakeS3Client:
    failures_before_success: int = 0
    attempts: int = 0
    uploads: list[tuple[str, str, str]] | None = None

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.attempts += 1
        if self.failures_before_success:
            self.failures_before_success -= 1
            raise RuntimeError("temporary upload failure")
        if self.uploads is None:
            self.uploads = []
        self.uploads.append((filename, bucket, key))


class FakeBoto3:
    def __init__(self, failures_before_success: int = 0):
        self.s3_client = FakeS3Client(failures_before_success=failures_before_success)
        self.client_kwargs = {}

    def client(self, *args, **kwargs):
        self.client_kwargs = {"service_name": args[0], **kwargs}
        return self.s3_client


def _files(tmp_path: Path) -> MeetingFiles:
    audio = tmp_path / "recording.m4a"
    markdown = tmp_path / "transcript.md"
    audio.write_bytes(b"audio")
    markdown.write_text("# Meeting\n", encoding="utf-8")
    return MeetingFiles(
        meta=MeetingMeta(
            slug="2026-06-10_09-00_product-sync",
            started_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            calendar_title="Product Sync",
        ),
        directory=tmp_path,
        audio_path=audio,
        markdown_path=markdown,
    )
