"""Keep a bounded glossary on reset Whisper windows without retaining prior speech."""

from contextlib import contextmanager
from dataclasses import replace


@contextmanager
def persistent_vocabulary(model, prompt: str | None):
    """Adapt the pinned Whisper decoder for this one ephemeral inference model.

    ``generate`` discards its initial prompt with previous-text conditioning off.
    Reinsert only the static glossary on empty-prompt windows, never prior speech.
    The normal initial prompt and temperature-fallback prompts remain unchanged.
    """
    if not prompt:
        yield
        return
    original_decode = model.decode
    tokens = {}

    def decode(audio, options, **kwargs):
        if not options.prompt:
            key = (options.language, options.task)
            if key not in tokens:
                tokenizer = model.get_tokenizer(language=options.language, task=options.task)
                tokens[key] = tokenizer.encode(" " + prompt.strip())
            options = replace(options, prompt=list(tokens[key]))
        return original_decode(audio, options, **kwargs)

    model.decode = decode
    try:
        yield
    finally:
        model.decode = original_decode
