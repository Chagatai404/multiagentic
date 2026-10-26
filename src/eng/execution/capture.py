"""Bounded capture with streaming redaction before any disk persistence."""

import codecs
import json
import os
import re
from pathlib import Path
from typing import BinaryIO

_NAMES = re.compile(r"(?:token|secret|password|api.?key|credential|private.?key)", re.I)
_PAIR = re.compile(
    r"(?i)([\"']?(?:token|secret|password|api[_-]?key|credential|private[_-]?key)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)"
)
_QUOTED_PREFIX = re.compile(
    r"(?i)([\"']?(?:token|secret|password|api[_-]?key|credential|private[_-]?key)"
    r"[\"']?\s*[:=]\s*[\"'])"
)
_BEARER = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/-]+)")
_INCOMPLETE = re.compile(
    r"(?i)(?:token|secret|password|api[_-]?key|credential|private[_-]?key|bearer)"
    r"[\"']?\s*(?:[:=]\s*)?[\"']?\s*$"
)
_JSON_NUMBER = re.compile(
    r"(?:^|[\[,:])\s*(?P<number>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
    r"(?:[eE][+-]?[0-9]+)?)(?=\s*(?:[,}\]]|$))"
)


class StreamRedactor:
    """Keep finite lookbehind and discard secret values incrementally, even huge ones.

    Credential names/prefix whitespace are bounded to 4096 characters. Environment
    secrets extend the lookbehind as necessary. Secret values have no length limit.
    """

    def __init__(self) -> None:
        self.secrets = sorted(
            {v for k, v in os.environ.items() if _NAMES.search(k) and len(v) >= 6},
            key=len,
            reverse=True,
        )
        self.hold = max([4096, *(len(v) + 32 for v in self.secrets)])
        self.pending = ""
        self.skipping: re.Pattern[str] | None = None
        self.quoted: str | None = None
        self.quote_escape = False
        self.preserve_numbers = False

    def _quote_end(self, text: str, start: int, quote: str) -> int:
        for index in range(start, len(text)):
            char = text[index]
            if self.quote_escape:
                self.quote_escape = False
            elif char == "\\":
                self.quote_escape = True
            elif char == quote:
                return index
        return len(text)

    def feed(self, text: str, *, final: bool = False) -> str:
        if self.quoted is not None:
            end = self._quote_end(text, 0, self.quoted)
            if end == len(text) and not final:
                return ""
            text = text[end:]
            self.quoted = None
        if self.skipping is not None:
            match = self.skipping.match(text)
            consumed = match.end() if match else 0
            text = text[consumed:]
            if not text and not final:
                return ""
            self.skipping = None
        self.pending += text
        output: list[str] = []
        while self.pending:
            safe = len(self.pending) if final else len(self.pending) - self.hold
            if safe <= 0:
                break
            candidates: list[tuple[int, int, str, re.Pattern[str] | None, str | None]] = []
            quoted = _QUOTED_PREFIX.search(self.pending)
            if quoted:
                quote = quoted[1][-1]
                self.quote_escape = False
                end = self._quote_end(self.pending, quoted.end(), quote)
                candidates.append((quoted.start(), end, quoted[1] + "[REDACTED]", None, quote))
            for pattern, continuation in (
                (_PAIR, re.compile(r"[^\s\"',}]+")),
                (_BEARER, re.compile(r"[A-Za-z0-9._~+/-]+")),
            ):
                match = pattern.search(self.pending)
                if match:
                    quote = None
                    end = match.end()
                    if pattern is _PAIR and match[1][-1:] in {'"', "'"}:
                        continue  # The quoted-prefix matcher also handles leading whitespace.
                    candidates.append(
                        (match.start(), end, match[1] + "[REDACTED]", continuation, quote)
                    )
            numbers = list(_JSON_NUMBER.finditer(self.pending)) if self.preserve_numbers else []
            for secret in self.secrets:
                index = self.pending.find(secret)
                if index >= 0:
                    end = index + len(secret)
                    if not any(
                        number.start("number") <= index and end <= number.end("number")
                        for number in numbers
                    ):
                        candidates.append((index, end, "[REDACTED]", None, None))
            first = min(candidates, key=lambda item: item[0]) if candidates else None
            if first is None or first[0] >= safe:
                incomplete = _INCOMPLETE.search(self.pending)
                if not final and incomplete and incomplete.start() < safe:
                    raise ValueError("Credential prefix exceeds redaction lookbehind")
                output.append(self.pending[:safe])
                self.pending = self.pending[safe:]
                break
            start, end, replacement, next_pattern, quote = first
            # A shorter assignment match must never split an overlapping known
            # environment credential containing spaces or punctuation.
            for other in sorted(candidates, key=lambda item: item[0]):
                if other[0] < end and other[1] > end:
                    end = other[1]
            output.extend((self.pending[:start], replacement))
            if end == len(self.pending) and not final:
                if quote is not None:
                    self.quoted = quote
                else:
                    self.skipping = next_pattern
            self.pending = self.pending[end:]
        return "".join(output)


class JsonStreamRedactor:
    """Redact decoded JSON strings and preserve numeric protocol fields verbatim."""

    def __init__(self) -> None:
        self.inside = False
        self.escape = ""
        self.string = StreamRedactor()
        self.key = ""
        self.last_key = ""
        self.sensitive = False
        self.mask = False
        self.high_surrogate: int | None = None
        self.key_sensitive = False
        self.last_sensitive = False
        self.outside = StreamRedactor()
        # Numbers are protocol counters, not string credentials.
        self.outside.preserve_numbers = True
        self.depth = 0

    def feed(self, text: str, *, final: bool = False) -> str:
        output: list[str] = []
        decoded: list[str] = []
        outside: list[str] = []

        def scalar(value: str) -> None:
            number = ord(value) if len(value) == 1 else 0
            if self.high_surrogate is not None:
                if 0xDC00 <= number <= 0xDFFF:
                    decoded.append(
                        chr(0x10000 + ((self.high_surrogate - 0xD800) << 10) + number - 0xDC00)
                    )
                    self.high_surrogate = None
                    return
                decoded.append("\ufffd")
                self.high_surrogate = None
            if 0xD800 <= number <= 0xDBFF:
                self.high_surrogate = number
            elif 0xDC00 <= number <= 0xDFFF:
                decoded.append("\ufffd")
            else:
                decoded.append(value)

        def flush(*, end: bool = False) -> None:
            value = "".join(decoded)
            decoded.clear()
            self.key_sensitive = self.key_sensitive or bool(_NAMES.search(self.key + value))
            self.key = (self.key + value)[-32:]
            if not self.mask:
                clean = self.string.feed(value, final=end)
                output.append(json.dumps(clean, ensure_ascii=True)[1:-1])

        for char in text:
            if not self.inside:
                if char == '"':
                    output.append(self.outside.feed("".join(outside), final=True))
                    outside.clear()
                    self.inside = True
                    self.string = StreamRedactor()
                    self.key = ""
                    self.key_sensitive = False
                    self.mask = self.sensitive
                    self.sensitive = False
                    output.append('"' + ("[REDACTED]" if self.mask else ""))
                else:
                    if self.depth == 0 and not char.isspace() and char != "{":
                        # Provider protocols require object roots. Bare numeric
                        # credentials are malformed protocol, not usage counters.
                        self.outside.preserve_numbers = False
                    if char in "{[":
                        self.depth += 1
                    elif char in "}]":
                        self.depth -= 1
                    if char not in "{}[],: \t\r\n0123456789.eE+-truefalsn":
                        # Malformed plaintext uses ordinary secret redaction.
                        self.outside.preserve_numbers = False
                    if char == ":":
                        self.sensitive = self.last_sensitive
                    elif not char.isspace():
                        self.sensitive = False
                    outside.append(char)
                continue
            if self.escape:
                self.escape += char
                if self.escape == "\\u" or (self.escape.startswith("\\u") and len(self.escape) < 6):
                    continue
                try:
                    scalar(json.loads('"' + self.escape + '"'))
                except ValueError:
                    decoded.append("\ufffd")
                self.escape = ""
            elif char == "\\":
                self.escape = char
            elif char == '"':
                if self.high_surrogate is not None:
                    decoded.append("\ufffd")
                    self.high_surrogate = None
                flush(end=True)
                output.append('"')
                self.last_key = self.key
                self.last_sensitive = self.key_sensitive
                self.inside = False
            else:
                decoded.append(char)
        if self.inside:
            flush(end=final)
        else:
            output.append(self.outside.feed("".join(outside), final=final))
        return "".join(output)


class Capture:
    def __init__(self, path: Path | None, limit: int, *, json_output: bool = False) -> None:
        self.path = path
        self.limit = max(0, limit)
        self.raw_bytes = 0
        self.artifact_bytes = 0
        self.redacted_bytes = 0
        self.excerpt = bytearray()
        self.complete = False
        self.error: str | None = None
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.redactor = JsonStreamRedactor() if json_output else StreamRedactor()
        self.sink: BinaryIO | None = None
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.sink = path.open("wb")
            except OSError as error:
                self.error = type(error).__name__

    def _write(self, text: str) -> None:
        encoded = text.encode("utf-8")
        self.redacted_bytes += len(encoded)
        self.excerpt.extend(encoded[: max(0, self.limit - len(self.excerpt))])
        if self.sink is not None and self.error is None:
            try:
                self.sink.write(encoded)
                self.artifact_bytes += len(encoded)
            except OSError as error:
                self.error = type(error).__name__

    def feed(self, chunk: bytes) -> None:
        self.raw_bytes += len(chunk)
        if self.error is None:
            try:
                self._write(self.redactor.feed(self.decoder.decode(chunk)))
            except ValueError as error:
                self.error = type(error).__name__

    def finish(self) -> None:
        if self.error is None:
            try:
                self._write(self.redactor.feed(self.decoder.decode(b"", final=True), final=True))
            except (ValueError, OSError) as error:
                self.error = type(error).__name__
        if self.sink is not None:
            try:
                self.sink.close()
            except OSError as error:
                self.error = type(error).__name__
        self.complete = self.error is None

    @property
    def text(self) -> str:
        return self.excerpt.decode("utf-8", errors="replace")

    def metadata(self) -> dict[str, object]:
        return {
            "raw_bytes": self.raw_bytes,
            "artifact_bytes": self.artifact_bytes,
            "redacted_bytes": self.redacted_bytes,
            "excerpt_bytes": len(self.excerpt),
            "excerpt_truncated": self.redacted_bytes > len(self.excerpt),
            "complete": self.complete,
            "error": self.error,
        }


def save_metadata(path: Path, streams: dict[str, dict[str, object]]) -> None:
    path.write_text(json.dumps(streams, indent=2), encoding="utf-8")
