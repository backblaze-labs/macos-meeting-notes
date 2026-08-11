"""Source modules introduced by standalone distribution hardening."""

REQUIRED_DISTRIBUTION_SOURCE_FILES = (
    "version.py",
    "types/runtime_layout.py",
    "config/runtime_layout.py",
    "repo/native_layout.py",
    "service/bundle_self_check.py",
    "service/configuration_migration_paths.py",
)

REQUIRED_DISTRIBUTION_REPO_FILES = (
    "docs/standalone-validation-evidence.md",
    "scripts/build_distribution.py",
    "scripts/distribution_signature.py",
    "scripts/release_distribution.py",
    "scripts/validate_release_context.py",
    "scripts/verify_distribution.py",
)
