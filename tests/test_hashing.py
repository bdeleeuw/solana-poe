import hashlib
from pathlib import Path

from solana_poe.hashing import hash_file, hash_paths


def test_hash_file_no_salt(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    assert hash_file(f) == hashlib.sha256(b"hello world").hexdigest()


def test_hash_file_custom_algorithm(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    assert hash_file(f, algorithm="sha512") == hashlib.sha512(b"hello world").hexdigest()


def test_hash_file_with_salt_matches_manual_computation(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"some/salted/path\x00hello world").hexdigest()
    assert hash_file(f, salt="some/salted/path") == expected


def test_hash_paths_on_directory_full_path_is_absolute(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"two")

    results = hash_paths([tmp_path])
    full_paths = {r.full_path for r in results}
    assert full_paths == {
        str((tmp_path / "a.txt").resolve()),
        str((sub / "b.txt").resolve()),
    }
    assert all(Path(p).is_absolute() for p in full_paths)


def test_hash_paths_on_directory_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"two")

    results = hash_paths([tmp_path], recursive=False)
    assert {r.full_path for r in results} == {str((tmp_path / "a.txt").resolve())}


def test_hash_paths_salts_by_path_so_identical_content_differs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"same content")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.txt").write_bytes(b"same content")

    results = hash_paths([tmp_path])
    digests = {r.full_path: r.digest for r in results}
    assert (
        digests[str((tmp_path / "a.txt").resolve())]
        != digests[str((sub / "a.txt").resolve())]
    )


def test_hash_paths_matches_hash_file_with_explicit_salt(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello world")

    (result,) = hash_paths([tmp_path])
    assert result.digest == hash_file(tmp_path / "a.txt", salt=result.full_path)


def test_hash_paths_on_a_single_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one")
    (tmp_path / "b.txt").write_bytes(b"two")

    (result,) = hash_paths([tmp_path / "a.txt"])
    assert result.full_path == str((tmp_path / "a.txt").resolve())


def test_hash_paths_on_a_glob_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one")
    (tmp_path / "b.txt").write_bytes(b"two")
    (tmp_path / "c.md").write_bytes(b"three")

    results = hash_paths([str(tmp_path / "*.txt")])
    full_paths = {r.full_path for r in results}
    assert full_paths == {
        str((tmp_path / "a.txt").resolve()),
        str((tmp_path / "b.txt").resolve()),
    }
