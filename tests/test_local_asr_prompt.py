"""Static vocabulary survives reset windows while prior speech is never carried."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from meeting_memory.repo.local_asr_prompt import persistent_vocabulary


@dataclass(frozen=True)
class Options:
    language: str = "en"
    task: str = "transcribe"
    prompt: object = None
    temperature: float = 0


def test_vocabulary_is_reused_on_reset_windows_without_prior_speech():
    calls, encoded = [], []

    def encode(text):
        encoded.append(text)
        return [1, 2, 3]

    def original(audio, options):
        calls.append(options)
    model = SimpleNamespace(
        decode=original,
        get_tokenizer=lambda **_: SimpleNamespace(encode=encode),
    )
    initial = Options(prompt=[1, 2, 3])
    with persistent_vocabulary(model, "Vocabulary: SDK"):
        model.decode("first window", initial)
        model.decode("second window", Options(prompt=[]))
        model.decode("third window", Options(prompt=[], temperature=0.4))
    assert model.decode is original
    assert calls[0] is initial
    assert [item.prompt for item in calls] == [[1, 2, 3]] * 3
    assert calls[-1].temperature == 0.4
    assert encoded == [" Vocabulary: SDK"]


def test_decoder_is_restored_when_generate_or_decode_fails():
    def fail(*_args, **_kwargs):
        raise RuntimeError("inference failed")

    model = SimpleNamespace(
        decode=fail,
        get_tokenizer=lambda **_: SimpleNamespace(encode=lambda _: [1]),
    )
    with pytest.raises(RuntimeError):
        with persistent_vocabulary(model, "Vocabulary: SDK"):
            model.decode("audio", Options())
    assert model.decode is fail


def test_absent_glossary_leaves_decoder_untouched():
    model = SimpleNamespace(decode=object())
    original = model.decode
    with persistent_vocabulary(model, None):
        assert model.decode is original
    assert model.decode is original
