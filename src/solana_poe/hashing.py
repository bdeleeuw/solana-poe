from __future__ import annotations

import glob as glob_module
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Union

DEFAULT_ALGORITHM = "sha256"
_CHUNK_SIZE = 1024 * 1024
_SALT_SEPARATOR = b"\x00"

PathSpec = Union[str, Path]


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


def resolve_targets(specs: Iterable[PathSpec], recursive: bool = True) -> List[Path]:
    """Expand a mix of file paths, directory paths, and glob patterns into
    a deduplicated list of file paths, in the order encountered.

    Each spec is resolved as:
      - an existing file -> itself
      - an existing directory -> every file under it (`recursive` controls
        whether subdirectories are walked)
      - anything else -> treated as a glob pattern (`*`, `?`, `[...]`, and
        `**` for recursive matching are all supported); every match that's
        a file is included, every match that's a directory has its files
        included (again respecting `recursive`)

    A spec that is neither an existing path nor a glob pattern with at
    least one match raises FileNotFoundError.
    """
    resolved: List[Path] = []
    seen = set()

    def add(path: Path) -> None:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            resolved.append(path)

    def add_from(path: Path) -> None:
        if path.is_dir():
            for f in iter_files(path, recursive=recursive):
                add(f)
        else:
            add(path)

    for spec in specs:
        spec_str = str(spec)
        if not spec_str:
            # Path("").is_dir() is True (it normalizes to "."), so without
            # this check an empty string -- e.g. an unset shell variable
            # interpolated into the command line -- would silently expand
            # to "every file under the current directory" instead of
            # erroring. Caught live: `solana-poe hash ''` hashed 3800+
            # files including .git internals with no warning.
            raise ValueError(
                "empty path specification (an empty string is not a valid "
                "file, directory, or glob pattern)"
            )
        p = Path(spec_str)
        if p.is_file() or p.is_dir():
            add_from(p)
            continue

        matches = sorted(glob_module.glob(spec_str, recursive=True))
        if not matches:
            raise FileNotFoundError(f"{spec_str!r} does not exist and matches no files")
        for m in matches:
            add_from(Path(m))

    return resolved


def hash_paths(
    specs: Iterable[PathSpec], algorithm: str = DEFAULT_ALGORITHM, recursive: bool = True
) -> List[FileHash]:
    """Hash every file resolved from `specs` -- each may be a file, a
    directory, or a glob pattern; see `resolve_targets`.

    Each digest is salted with that file's full (resolved, absolute)
    filesystem path, so the digest is bound to both the file's content
    and its exact location on disk. `full_path` on each result is that
    same salted path string, and is also what gets recorded in the
    manifest by the CLI.
    """
    results = []
    for path in resolve_targets(specs, recursive=recursive):
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
