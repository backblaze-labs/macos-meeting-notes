"""Formatting-only coalescing of consecutive displayed speaker turns."""

import re

TRANSCRIPT_LINE = re.compile(r"^\*\*(?P<label>[^*\r\n]+)\*\* \(\d+:\d\d:\d\d\): (?P<text>.+)$")


def coalesce_transcript_turns(body: str) -> str:
    """Keep first timestamps and every text token, without crossing other content."""
    output: list[str] = []
    blanks: list[str] = []
    previous_label = None
    for line in body.splitlines(keepends=True):
        if not line.strip():
            blanks.append(line)
            continue
        content = line.rstrip("\r\n")
        match = TRANSCRIPT_LINE.fullmatch(content)
        if match and match.group("label") == previous_label:
            previous = output[-1].rstrip("\r\n")
            text = match.group("text")
            separator = "" if previous[-1].isspace() or text[0].isspace() else " "
            output[-1] = previous + separator + text + line[len(content) :]
        else:
            output.extend(blanks)
            output.append(line)
        blanks.clear()
        previous_label = match.group("label") if match else None
    output.extend(blanks)
    return "".join(output)
