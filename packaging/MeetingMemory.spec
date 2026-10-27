# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata,
)

ROOT = Path(SPECPATH).parent
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

from meeting_memory.version import APP_VERSION, BUNDLE_BUILD

ARCH = os.environ["MEETING_MEMORY_TARGET_ARCH"]
SIGNING_IDENTITY = os.environ.get("MEETING_MEMORY_CODESIGN_IDENTITY") or None
ICON = ROOT / "src/meeting_memory/service/assets/MeetingMemory.icns"

datas = [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "packaging/FFMPEG_SOURCE_OFFER.md"), "."),
    (str(ROOT / "src/meeting_memory/ui/assets/robot-template.png"), "meeting_memory/ui/assets"),
    (str(ROOT / "src/meeting_memory/ui/assets/robot-template.svg"), "meeting_memory/ui/assets"),
]
datas += collect_data_files("botocore")
datas += collect_data_files("certifi")
datas += copy_metadata("macos-meeting-notes", recursive=True)

hiddenimports = [
    "AppKit",
    "Foundation",
    "anthropic",
    "assemblyai",
    "boto3",
    "cryptography.hazmat.backends",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat.primitives._serialization",
    "cryptography.hazmat.primitives.asymmetric.ec",
    "cryptography.hazmat.primitives.asymmetric.rsa",
    "cryptography.hazmat.primitives.asymmetric.utils",
    "cryptography.hazmat.primitives.hashes",
    "cryptography.x509",
    "google.auth._service_account_info",
    "google.auth.crypt._cryptography_rsa",
    "google.auth.crypt.base",
    "google.auth.crypt.es",
    "google.auth.crypt.es256",
    "google.auth.crypt.rsa",
    "google.auth.crypt",
    "google.auth.external_account_authorized_user",
    "google.auth.iam",
    "google.auth.jwt",
    "google.auth.transport._mtls_helper",
    "google.auth.transport.requests",
    "google.oauth2._client",
    "google.oauth2.credentials",
    "google.oauth2.service_account",
    "google_auth_oauthlib.flow",
    "google_auth_oauthlib.helpers",
    "googleapiclient.discovery",
    "requests",
    "requests.adapters",
    "requests.exceptions",
    "requests_oauthlib",
    "rumps",
    "urllib3.util.ssl_",
]

local_binaries = []
if ARCH == "arm64":
    for package in ("mlx", "mlx_audio"):
        datas += collect_data_files(package)
    local_binaries += collect_dynamic_libs("mlx")
    for package in (
        "mlx", "mlx_audio.stt.models.whisper", "mlx_audio.vad.models.nemotron_diarization",
        "mlx_audio.vad.models.sortformer",
    ):
        hiddenimports += collect_submodules(package)
    hiddenimports += [
        "mlx.core", "mlx.nn", "mlx_audio.stt", "mlx_audio.vad", "huggingface_hub",
        "miniaudio", "numpy", "scipy", "transformers",
    ]
datas += [(str(ROOT / "src/meeting_memory/repo/local_model_manifest.json"), "meeting_memory/repo")]

a = Analysis(
    [str(ROOT / "src/meeting_memory/__main__.py")],
    pathex=[str(SOURCE)],
    binaries=local_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "keyring.backends.SecretService",
        "keyring.backends.Windows",
        "keyring.backends.kwallet",
        "keyring.backends.libsecret",
        "meeting_memory.ui.notes_prompt",
        "meeting_memory.ui.preferences",
        "pytest",
        "ruff",
    ],
    noarchive=False,
    optimize=0,
)
# Tokenizers' optional public CycloneDX SBOM matches the credential denylist.
# It is unused at runtime; omit only this file and retain metadata and licenses.
a.datas = [
    entry for entry in a.datas
    if entry[0] != "tokenizers-0.23.3.dist-info/sboms/tokenizers-python.cyclonedx.json"
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Meeting Memory",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=ARCH,
    codesign_identity=SIGNING_IDENTITY,
    entitlements_file=None,
    icon=[str(ICON)],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Meeting Memory",
)
app = BUNDLE(
    coll,
    name="Meeting Memory.app",
    icon=str(ICON),
    bundle_identifier="com.meeting-memory.app",
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": "Meeting Memory",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": BUNDLE_BUILD,
        "LSMinimumSystemVersion": "15.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": (
            "Meeting Memory records meeting audio when you start a recording."
        ),
        "NSScreenCaptureUsageDescription": (
            "Meeting Memory captures system audio only while you record a meeting."
        ),
    },
    target_arch=ARCH,
    codesign_identity=SIGNING_IDENTITY,
    entitlements_file=None,
)
