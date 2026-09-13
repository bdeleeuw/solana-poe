from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

DEFAULT_ALGORITHM = "sha256"
_CHUNK_SIZE = 1024 * 1024
_SALT_SEPARATOR = b"\x00"


@dataclass(frozen=True)
class FileHash:
    path: Path
    full_path: str
    algorithm: str
    digest: str
    size: int


def hash_file(path: Path, algorithm: str = DEFAULT_ALGORITHM, salt: Optional[str] = None) -> str:
    """Return the hex digest of a single file, read in chunks.

    If `salt` is given, the digest covers `salt.encode("utf-8") + b"\\x00"
    + <file bytes>` instead of just the file bytes, so identical content
    under a different salt produces a different digest.
    """
    hasher = hashlib.new(algorithm)
    if salt is not None:
        hasher.update(salt.encode("utf-8"))
        hasher.update(_SALT_SEPARATOR)
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def iter_files(directory: Path, recursive: bool = True) -> Iterator[Path]:
    pattern = "**/*" if recursive else "*"
    for path in sorted(Path(directory).glob(pattern)):
        if path.is_file():
            yield path


def hash_directory(
    directory: Path, algorithm: str = DEFAULT_ALGORITHM, recursive: bool = True
) -> List[FileHash]:
    """Hash every file under `directory`.

    Each digest is salted with that file's full (resolved, absolute)
    filesystem path, so the digest is bound to both the file's content
    and its exact location on disk. `full_path` on each result is that
    same salted path string, and is also what gets recorded in the
    manifest by the CLI.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"{directory} is not a directory")

    results = []
    for path in iter_files(directory, recursive=recursive):
        resolved = path.resolve()
        full_path = str(resolved)
        digest = hash_file(path, algorithm, salt=full_path)
        results.append(
            FileHash(
                path=resolved,
                full_path=full_path,
                algorithm=algorithm,
                digest=digest,
                size=path.stat().st_size,
            )
        )
    return results
