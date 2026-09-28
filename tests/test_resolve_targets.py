from pathlib import Path

import pytest

from solana_poe.hashing import resolve_targets


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.write_bytes(content)
    return path


def test_resolve_targets_single_file(tmp_path: Path) -> None:
    f = _touch(tmp_path / "a.txt")
    assert resolve_targets([f]) == [f]


def test_resolve_targets_directory_returns_every_file(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    sub = tmp_path / "sub"
    sub.mkdir()
    b = _touch(sub / "b.txt")

    result = resolve_targets([tmp_path])
    assert {p.resolve() for p in result} == {a.resolve(), b.resolve()}


def test_resolve_targets_directory_non_recursive(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    sub = tmp_path / "sub"
    sub.mkdir()
    _touch(sub / "b.txt")

    result = resolve_targets([tmp_path], recursive=False)
    assert {p.resolve() for p in result} == {a.resolve()}


def test_resolve_targets_glob_pattern_matches_only_matching_files(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    b = _touch(tmp_path / "b.txt")
    _touch(tmp_path / "c.md")

    result = resolve_targets([str(tmp_path / "*.txt")])
    assert {p.resolve() for p in result} == {a.resolve(), b.resolve()}


def test_resolve_targets_recursive_double_star_glob(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    sub = tmp_path / "sub"
    sub.mkdir()
    b = _touch(sub / "b.txt")

    result = resolve_targets([str(tmp_path / "**" / "*.txt")])
    assert {p.resolve() for p in result} == {a.resolve(), b.resolve()}


def test_resolve_targets_glob_matching_a_directory_expands_its_files(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    a = _touch(sub / "a.txt")

    result = resolve_targets([str(tmp_path / "sub*")])
    assert {p.resolve() for p in result} == {a.resolve()}


def test_resolve_targets_nonexistent_non_glob_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        resolve_targets([str(tmp_path / "nope.txt")])


def test_resolve_targets_glob_with_no_matches_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist and matches no files"):
        resolve_targets([str(tmp_path / "*.nonexistent")])


def test_resolve_targets_mixed_specs_are_unioned(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    sub = tmp_path / "sub"
    sub.mkdir()
    b = _touch(sub / "b.txt")
    other = _touch(tmp_path / "other.md")

    result = resolve_targets([str(a), str(sub), str(tmp_path / "*.md")])
    assert {p.resolve() for p in result} == {a.resolve(), b.resolve(), other.resolve()}


def test_resolve_targets_deduplicates_overlapping_specs(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")

    result = resolve_targets([str(a), str(a), str(tmp_path / "*.txt")])
    assert len(result) == 1
    assert result[0].resolve() == a.resolve()


def test_resolve_targets_rejects_empty_string_spec() -> None:
    # Regression test: Path("").is_dir() is True (normalizes to "."), so
    # without an explicit check an empty string -- e.g. an unset shell
    # variable interpolated into the command line -- silently expanded to
    # "every file under the current directory" instead of erroring. Found
    # live: `solana-poe hash ''` hashed 3800+ files including .git
    # internals, no warning. This must raise, not silently use cwd.
    with pytest.raises(ValueError, match="empty path specification"):
        resolve_targets([""])


def test_resolve_targets_empty_string_rejected_even_alongside_valid_specs(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.txt")
    with pytest.raises(ValueError, match="empty path specification"):
        resolve_targets([str(a), ""])


def test_resolve_targets_directory_mode_includes_dotfiles_glob_mode_does_not(tmp_path: Path) -> None:
    # Documented, intentional asymmetry (matches standard shell/glob
    # semantics: unquoted "*" never matches dotfiles without dotglob) --
    # not a bug, but locked in here so a future change notices it.
    _touch(tmp_path / ".hidden.txt")
    visible = _touch(tmp_path / "a.txt")

    dir_result = {p.name for p in resolve_targets([tmp_path])}
    glob_result = {p.name for p in resolve_targets([str(tmp_path / "*")])}

    assert dir_result == {".hidden.txt", "a.txt"}
    assert glob_result == {"a.txt"}
    assert visible.name in glob_result


def test_resolve_targets_does_not_traverse_a_symlinked_subdirectory(tmp_path: Path) -> None:
    # Known limitation (pre-existing, not introduced by the glob rework):
    # pathlib's Path.glob("**/*") does not follow a symlink to a directory
    # nested inside the directory being walked. A symlink passed AS the
    # spec directly (see the file/dir cases above) is followed fine --
    # only a symlinked subdirectory encountered during a walk is missed.
    real_target = tmp_path / "real_target"
    real_target.mkdir()
    _touch(real_target / "inner.txt")

    top = tmp_path / "top"
    top.mkdir()
    (top / "linked_sub").symlink_to(real_target, target_is_directory=True)

    assert resolve_targets([top]) == []
