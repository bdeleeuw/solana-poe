from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ManifestEntry:
    full_path: str
    algorithm: str
    hash: str
    size: int
    signature: Optional[str] = None
    slot: Optional[int] = None
    block_time: Optional[int] = None
    cluster: Optional[str] = None
    rpc_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def write_manifest(entries: List[ManifestEntry], path: Path) -> None:
    Path(path).write_text(json.dumps([e.to_dict() for e in entries], indent=2) + "\n")


def read_manifest(path: Path) -> List[ManifestEntry]:
    """Load a manifest, raising `ValueError` with a clear message if the
    file isn't valid JSON or its entries don't match `ManifestEntry`'s
    schema, instead of letting a raw JSONDecodeError/TypeError propagate.
    """
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of manifest entries")

    entries = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: entry {i} is not a JSON object")
        try:
            entries.append(ManifestEntry(**item))
        except TypeError as exc:
            raise ValueError(f"{path}: entry {i} doesn't match the manifest schema: {exc}") from exc
    return entries
