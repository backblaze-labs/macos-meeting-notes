"""Static standalone-distribution contracts stay versioned and minimal."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from meeting_memory import __version__
from meeting_memory.service.macos_app import macos_app_plist
from meeting_memory.version import APP_VERSION, BUNDLE_BUILD

ROOT = Path(__file__).resolve().parents[1]


def test_version_has_one_python_source_and_matches_plist() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plist = macos_app_plist()

    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "meeting_memory.version.APP_VERSION"
    }
    assert __version__ == APP_VERSION
    assert plist["CFBundleShortVersionString"] == APP_VERSION
    assert plist["CFBundleVersion"] == BUNDLE_BUILD


def test_spec_is_onedir_windowed_and_has_minimal_security_metadata() -> None:
    text = (ROOT / "packaging/MeetingMemory.spec").read_text(encoding="utf-8")

    assert "COLLECT(" in text
    assert "BUNDLE(" in text
    assert "console=False" in text
    assert 'bundle_identifier="com.meeting-memory.app"' in text
    assert '"LSMinimumSystemVersion": "15.0"' in text
    assert "entitlements_file=None" in text
    assert 'collect_submodules("meeting_memory")' not in text
    assert '"meeting_memory.ui.preferences"' in text
    assert '"meeting_memory.ui.notes_prompt"' in text
    for oauth_import in (
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
        "requests.adapters",
        "requests.exceptions",
        "requests_oauthlib",
        "urllib3.util.ssl_",
    ):
        assert f'"{oauth_import}"' in text
    for forbidden in (
        "allow-jit",
        "allow-unsigned-executable-memory",
        "disable-library-validation",
        "get-task-allow",
    ):
        assert forbidden not in text


def test_distribution_lock_pins_packager_and_runtime_dependencies() -> None:
    lines = (ROOT / "requirements-distribution.lock").read_text(encoding="utf-8").splitlines()
    requirements = [line for line in lines if line and not line.startswith("#")]

    assert requirements[0] == "-e ."
    assert "pyinstaller==6.21.0" in requirements
    assert "anthropic==0.121.0" in requirements
    assert "boto3==1.43.68" in requirements
    assert "cryptography==48.0.1" in requirements
    assert all(item == "-e ." or "==" in item for item in requirements)


def test_ci_actions_are_immutable_and_use_node_24_generations() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    action_refs = re.findall(r"uses: [^@\s]+@([0-9a-f]{40})", text)

    assert len(action_refs) == 5
    assert "# v7" in text
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
