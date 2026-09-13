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
    data = json.loads(Path(path).read_text())
    return [ManifestEntry(**item) for item in data]
