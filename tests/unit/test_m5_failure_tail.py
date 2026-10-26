from pathlib import Path
from typing import BinaryIO, cast
from unittest.mock import patch

import pytest

from eng.core.engine import Engine
from eng.core.models import ProjectConfig, Task, TaskSpec, VerificationResult


@pytest.mark.parametrize(
    "suffix",
    [
        ("STDERR:\r\n失败😀\r\n" * 2000).encode() + b"FINAL FAILURE\r\n",
        "😀".encode() * 5000,
        b"invalid UTF8 \xff\xfe\r\nlast failure\r",
    ],
    ids=["mixed-newlines-multibyte-stderr", "exact-5000-four-byte-chars", "invalid-utf8"],
)
def test_failure_evidence_reads_bounded_tail_with_multibyte_stderr(
    tmp_path: Path, suffix: bytes
) -> None:
    task = Task(
        project=tmp_path,
        config=ProjectConfig(),
        spec=TaskSpec(description="Fix answer", acceptance=["passes"]),
    )
    artifact = tmp_path / ".engineering" / "artifacts" / task.id / "answer.log"
    artifact.parent.mkdir(parents=True)
    payload = b"large stdout\r\n" * 20000 + b"\nSTDERR:\n" + suffix
    artifact.write_bytes(payload)
    expected = payload.decode("utf-8", errors="replace").replace("\r\n", "\n")
    expected = expected.replace("\r", "\n")[-5000:]
    task.verification = [
        VerificationResult(
            check_id="answer",
            command=["check"],
            environment=str(tmp_path),
            outcome="FAIL",
            artifact=str(artifact),
        )
    ]
    opened = Path.open
    reads: list[int] = []

    class BoundedReader:
        def __init__(self, handle: BinaryIO) -> None:
            self.handle = handle

        def __enter__(self) -> "BoundedReader":
            return self

        def __exit__(self, *_: object) -> None:
            self.handle.close()

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.handle.seek(offset, whence)

        def read(self, size: int = -1) -> bytes:
            assert 0 <= size <= 20000, "Failure evidence must never read a whole artifact"
            reads.append(size)
            return self.handle.read(size)

    def guarded_open(path: Path, mode: str) -> BoundedReader:
        assert path == artifact and mode == "rb"
        return BoundedReader(cast(BinaryIO, opened(path, mode)))

    with (
        patch.object(Path, "open", guarded_open),
        patch.object(Path, "read_text", side_effect=AssertionError("whole-file text read")),
        patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file bytes read")),
    ):
        evidence = Engine._failure_evidence(task)
    assert evidence == "answer: FAIL\n" + expected
    assert reads == [20000]
