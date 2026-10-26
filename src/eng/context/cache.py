"""Execution-local decoded-reference cache; current bounded bytes are always hashed."""

import hashlib
from collections import OrderedDict
from pathlib import Path


class ContextCache:
    """Bound retained UTF-8 material; callers revalidate membership/policy before every read.

    This stores no objectives, evidence, handoffs or diffs and writes nothing to disk.
    The key includes workspace, Git HEAD, policy, path and the current read limit.
    """

    def __init__(self, max_bytes: int = 1_000_000, max_entries: int = 128) -> None:
        if not 1 <= max_bytes <= 16_000_000 or not 1 <= max_entries <= 1024:
            raise ValueError("Invalid context cache bounds")
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._entries: OrderedDict[bytes, tuple[bytes, str, int]] = OrderedDict()
        self._retained = 0
        self._stats = dict(hits=0, misses=0, hash_bytes=0, decode_bytes=0, evictions=0)

    def read(self, target: Path, limit: int, *, scope: tuple[str, ...]) -> str:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 4_000_000:
            raise ValueError("Invalid bounded context read limit")
        with target.open("rb") as handle:
            source = handle.read(limit)
        self._stats["hash_bytes"] += len(source)
        digest = hashlib.sha256(source).digest()
        key = hashlib.sha256(repr((*scope, str(target), str(limit))).encode("utf-8")).digest()
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._retained -= previous[2]
            if previous[0] == digest:
                self._entries[key] = previous
                self._retained += previous[2]
                self._stats["hits"] += 1
                return previous[1]
        self._stats["misses"] += 1
        self._stats["decode_bytes"] += len(source)
        text = source.decode("utf-8", errors="replace")
        size = len(text.encode("utf-8"))
        if size <= self.max_bytes:
            while self._entries and (
                len(self._entries) >= self.max_entries or self._retained + size > self.max_bytes
            ):
                _, removed = self._entries.popitem(last=False)
                self._retained -= removed[2]
                self._stats["evictions"] += 1
            self._entries[key] = (digest, text, size)
            self._retained += size
        return text

    def clear(self) -> None:
        self._entries.clear()
        self._retained = 0

    def snapshot(self) -> dict[str, int]:
        return {**self._stats, "entries": len(self._entries), "retained_bytes": self._retained}
