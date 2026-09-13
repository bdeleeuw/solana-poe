from pathlib import Path

import pytest

from solana_poe.manifest import ManifestEntry, read_manifest, write_manifest


def test_read_manifest_round_trips(tmp_path: Path) -> None:
    entries = [
        ManifestEntry(full_path="/a.txt", algorithm="sha256", hash="deadbeef", size=3)
    ]
    path = tmp_path / "manifest.json"
    write_manifest(entries, path)
    assert read_manifest(path) == entries


def test_read_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_manifest(path)


def test_read_manifest_rejects_non_list_top_level(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"not": "a list"}')
    with pytest.raises(ValueError, match="JSON array"):
        read_manifest(path)


def test_read_manifest_rejects_entry_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('[{"full_path": "/a.txt", "hash": "abc"}]')
    with pytest.raises(ValueError, match="doesn't match the manifest schema"):
        read_manifest(path)


def test_read_manifest_rejects_entry_with_unexpected_field(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '[{"full_path": "/a.txt", "algorithm": "sha256", "hash": "abc", '
        '"size": 1, "unexpected_field": true}]'
    )
    with pytest.raises(ValueError, match="doesn't match the manifest schema"):
        read_manifest(path)


def test_read_manifest_rejects_non_object_entry(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('["not an object"]')
    with pytest.raises(ValueError, match="not a JSON object"):
        read_manifest(path)
