"""Confirmed-only local history, privacy bounds, and names-only persistence."""

import os
from dataclasses import replace
from types import SimpleNamespace

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.config.settings import Settings
from meeting_memory.service.frontmatter import dump_frontmatter
from meeting_memory.service.preference_store import PreferenceStore
from meeting_memory.service.speaker_history import harvest_speaker_history
from meeting_memory.service.speaker_knowledge import SpeakerKnowledgeService
from meeting_memory.service.speaker_knowledge_offers import KnowledgeOfferStore
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceValue,
    SecretId,
    SecretRef,
)
from meeting_memory.types.speaker_knowledge import PersonTopic
from meeting_memory.types.speakers import KnownSpeaker


def meeting(root, slug="2026-01-01", *, aliases=None, status="confirmed", body=None, foreign=False):
    directory = root / slug
    directory.mkdir(parents=True)
    metadata = {
        "created_by": "foreign" if foreign else "meeting-memory",
        "schema_version": 2,
        "speaker_status": status,
        "speaker_aliases": aliases or {},
        "assemblyai_id": "private-provider-id",
        "date": "private-date",
    }
    (directory / "transcript.md").write_text(
        dump_frontmatter(metadata)
        + "\n"
        + (
            body
            or "**Alex** (0:00:01): I maintain the SDK integration.\n"
            "**Casey** (0:00:02): I test releases and verify quality.\n"
        )
    )
    return directory


def service(tmp_path, people=(), topics=None, enabled=lambda: True):
    meetings = tmp_path / "meetings"
    settings = RuntimeSettings(_env_file=None, meetings_dir=meetings, known_speakers=people)
    store = PreferenceStore(tmp_path / "private" / "preferences.json")
    return (
        SpeakerKnowledgeService(settings, store=store, topics=topics, enabled=enabled),
        store,
        meetings,
    )


def test_harvest_only_confirmed_named_records_and_exact_names(tmp_path):
    root = tmp_path / "meetings"
    meeting(root, aliases={"A": "Alex", "B": "Casey"})
    meeting(root, "2026-01-02", aliases={"A": "Alex"}, status="needs_review")
    meeting(root, "2026-01-03", aliases={}, status="confirmed")
    meeting(root, "2026-01-04", aliases={"A": "Wrong"}, foreign=True)
    meeting(
        root,
        "2026-01-05",
        aliases={"A": "Alex Rivera"},
        body="**Alex Rivera** (0:00:01): I build tools.",
    )
    history = harvest_speaker_history(root)
    assert {p.name for p in history.people} == {"Alex", "Casey", "Alex Rivera"}
    assert history.meetings == 2
    assert next(p for p in history.people if p.name == "Casey").quotes == (
        "I test releases and verify quality.",
    )


def test_harvest_excludes_symlinks_and_oversized_files(tmp_path):
    root = tmp_path / "meetings"
    outside = meeting(tmp_path / "other", aliases={"A": "Outside"})
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    directory = meeting(root, aliases={"A": "Alex"})
    (directory / "transcript.md").write_text("x" * 2_097_153)
    assert not harvest_speaker_history(root).people


def test_fair_person_budget_and_meeting_limit(tmp_path):
    root = tmp_path / "meetings"
    names = [f"Person {i}" for i in range(20)]
    body = "\n".join(f"**{name}** (0:00:01): " + "x" * 3_500 for name in names)
    for i in range(25):
        meeting(
            root, f"2026-01-{i:02d}", aliases={str(i): n for i, n in enumerate(names)}, body=body
        )
    history = harvest_speaker_history(root)
    assert history.meetings == 20
    assert sum(sum(map(len, p.quotes)) for p in history.people) <= 60_000
    assert all(p.quotes for p in history.people)


def test_local_draft_preserves_roster_and_unrelated_prefs_until_save(tmp_path):
    existing = (KnownSpeaker("Alex", ("private@example.com", "alex-r"), "Existing context"),)
    svc, store, root = service(tmp_path, existing)
    original = AppPreferences(
        values=(PreferenceValue(PreferenceKey.GOOGLE_CALENDAR_ID, "all"),),
        capabilities=(CapabilityPreference(Capability.CALENDAR, False),),
        secret_refs=(SecretRef(SecretId.NOTES, "a" * 32),),
    )
    store.save(original)
    meeting(root, aliases={"A": "Alex", "B": "Casey"})
    draft = svc.draft(include_history=True)
    assert draft.people == (*existing, KnownSpeaker("Casey"))
    assert store.load_snapshot().preferences == original
    svc.cancel(draft.token)
    assert "expired" in svc.save(draft)
    assert store.load_snapshot().preferences == original
    assert "reopen" in svc.save(svc.draft(include_history=True))
    updated = store.load_snapshot().preferences
    assert (
        updated.capabilities == original.capabilities
        and updated.secret_refs == original.secret_refs
    )
    assert updated.value_for(PreferenceKey.GOOGLE_CALENDAR_ID) == "all"
    assert (
        Settings.parse_known_speakers(updated.value_for(PreferenceKey.KNOWN_SPEAKERS))
        == draft.people
    )


def test_concurrent_calendar_save_is_not_overwritten(tmp_path):
    svc, store, _ = service(tmp_path)
    draft = svc.draft(include_history=True)
    store.compare_and_swap(
        store.load_snapshot(),
        AppPreferences(values=(PreferenceValue(PreferenceKey.GOOGLE_CALENDAR_ID, "primary"),)),
    )
    assert "changed elsewhere" in svc.save(draft)
    assert (
        store.load_snapshot().preferences.value_for(PreferenceKey.GOOGLE_CALENDAR_ID) == "primary"
    )


def test_names_only_without_notes_or_when_paused_never_calls_provider(tmp_path):
    calls = []
    topics = SimpleNamespace(describe=lambda people: calls.append(people))
    svc, store, root = service(tmp_path, topics=topics, enabled=lambda: False)
    meeting(root, aliases={"A": "Alex"})
    draft = svc.suggest_topics(svc.draft(include_history=True))
    assert not calls and "paused" in draft.message
    assert "saved" in svc.save(draft)
    assert store.load_snapshot().preferences.value_for(PreferenceKey.KNOWN_SPEAKERS)


def test_topics_accept_only_exact_same_person_quotes_and_unique_names(tmp_path):
    topics = SimpleNamespace(
        describe=lambda _people: (
            PersonTopic("Alex", "SDK integrations", "I maintain the SDK integration."),
            PersonTopic("Casey", "QA", "I maintain the SDK integration."),
            PersonTopic("Stranger", "Untrusted", "I test releases and verify quality."),
        )
    )
    svc, _, root = service(tmp_path, topics=topics)
    meeting(root, aliases={"A": "Alex", "B": "Casey"})
    draft = svc.suggest_topics(svc.draft(include_history=True))
    assert draft.people == (
        KnownSpeaker("Alex", description="SDK integrations"),
        KnownSpeaker("Casey"),
    )
    topics.describe = lambda _people: (
        PersonTopic("Alex", "A", "I maintain"),
        PersonTopic("Alex", "B", "I maintain"),
    )
    assert all(
        not p.description for p in svc.suggest_topics(svc.draft(include_history=True)).people
    )


def test_offer_is_once_for_history_and_once_per_new_name_across_instances(tmp_path):
    svc, store, root = service(tmp_path)
    meeting(root, aliases={"A": "Alex"})
    assert svc.offer() == ("Alex",)
    assert not svc.offer()
    later = meeting(root, "2026-01-02", aliases={"A": "Casey"})
    assert svc.offer(later) == ("Casey",)
    other = SpeakerKnowledgeService(svc._settings, store=store)
    assert not other.offer(later)
    assert os.stat(store.path.parent / "speaker-onboarding.json").st_mode & 0o777 == 0o600
    assert "Casey" not in (store.path.parent / "speaker-onboarding.json").read_text()
    assert not KnowledgeOfferStore(tmp_path / "empty" / "offers.json").claim(())


def test_saved_empty_roster_is_authoritative_after_edit(tmp_path):
    svc, store, _ = service(tmp_path, (KnownSpeaker("Alex"),))
    draft = svc.draft()
    assert draft.people == (KnownSpeaker("Alex"),)
    assert "saved" in svc.save(replace(draft, people=()))
    assert store.load_snapshot().preferences.value_for(PreferenceKey.KNOWN_SPEAKERS) == "[]"
    assert svc.draft().people == ()


def test_v2_aliases_without_explicit_confirmed_status_are_excluded(tmp_path):
    root = tmp_path / "meetings"
    meeting(root, aliases={"A": "Alex"}, status=None)
    assert harvest_speaker_history(root).people == ()


def test_no_history_does_not_offer_or_write_suppression(tmp_path):
    svc, store, _ = service(tmp_path)
    assert svc.offer() == ()
    assert not (store.path.parent / "speaker-onboarding.json").exists()
