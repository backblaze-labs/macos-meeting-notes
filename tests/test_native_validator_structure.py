"""Mechanical safety checks for the native validator source."""

from pathlib import Path


def test_native_validator_bounds_untrusted_packet_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/meeting_memory/repo/native/NativeValidation.swift").read_text()

    assert "packetCount <= audioByteCount" in source
    assert "packetCount <= UInt64(Int64.max)" in source
    assert "maximumPacketSize <= maximumValidationPacketSize" in source
