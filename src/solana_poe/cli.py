from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

import click

from .client import CLUSTER_URLS, SolanaPoEClient, load_keypair, resolve_rpc_url
from .hashing import DEFAULT_ALGORITHM, hash_directory, hash_file
from .manifest import ManifestEntry, read_manifest, write_manifest
from .memo import MAX_MEMO_BYTES, MEMO_PROGRAM_ID_V1, MEMO_PROGRAM_ID_V2

MEMO_PROGRAM_IDS = {"v1": MEMO_PROGRAM_ID_V1, "v2": MEMO_PROGRAM_ID_V2}
DEFAULT_MEMO_PREFIX = "solana-poe:v1"


def _memo_program_id(name: str):
    return MEMO_PROGRAM_IDS[name]


@click.group()
@click.version_option()
def main() -> None:
    """Hash a directory of files and anchor the hashes on Solana via the Memo program."""


@main.command("hash")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--algo", default=DEFAULT_ALGORITHM, show_default=True, help="Hash algorithm (any hashlib name).")
@click.option("--recursive/--no-recursive", default=True, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), help="Write results as JSON to this file instead of stdout.")
def hash_cmd(directory: Path, algo: str, recursive: bool, output: Optional[Path]) -> None:
    """Hash every file in DIRECTORY. No blockchain interaction."""
    results = hash_directory(directory, algorithm=algo, recursive=recursive)
    payload = [
        {"full_path": r.full_path, "algorithm": r.algorithm, "hash": r.digest, "size": r.size}
        for r in results
    ]
    text = json.dumps(payload, indent=2)
    if output:
        Path(output).write_text(text + "\n")
        click.echo(f"wrote {len(payload)} hashes to {output}")
    else:
        click.echo(text)


@main.command("submit")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--keypair",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a Solana CLI JSON keypair file; pays fees and signs the memo transactions.",
)
@click.option("--cluster", type=click.Choice(sorted(CLUSTER_URLS)), default=None, help="Named cluster (default: devnet, ignored if --rpc-url is set).")
@click.option("--rpc-url", default=None, help="Custom RPC endpoint, overrides --cluster.")
@click.option("--algo", default=DEFAULT_ALGORITHM, show_default=True)
@click.option("--recursive/--no-recursive", default=True, show_default=True)
@click.option(
    "--combine/--no-combine",
    default=False,
    show_default=True,
    help="Pack multiple file hashes into as few memo transactions as possible instead of one transaction per file.",
)
@click.option("--memo-prefix", default=DEFAULT_MEMO_PREFIX, show_default=True)
@click.option("--memo-program", type=click.Choice(sorted(MEMO_PROGRAM_IDS)), default="v2", show_default=True)
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path),
    default=Path("solana-poe-manifest.json"),
    show_default=True,
    help="Where to write the receipt manifest.",
)
@click.option("--dry-run", is_flag=True, help="Hash files and print the memos that would be sent, without submitting anything.")
def submit_cmd(
    directory: Path,
    keypair: Path,
    cluster: Optional[str],
    rpc_url: Optional[str],
    algo: str,
    recursive: bool,
    combine: bool,
    memo_prefix: str,
    memo_program: str,
    manifest_path: Path,
    dry_run: bool,
) -> None:
    """Hash every file in DIRECTORY and post each hash to Solana as a Memo transaction."""
    results = hash_directory(directory, algorithm=algo, recursive=recursive)
    if not results:
        click.echo("no files found", err=True)
        sys.exit(1)

    lines = [f"{algo}:{r.digest}:{r.full_path}" for r in results]

    batches: list = []
    if combine:
        header_len = len(memo_prefix.encode("utf-8")) + 1 if memo_prefix else 0
        current: list = []
        current_len = header_len
        for idx, line in enumerate(lines):
            added_len = len(line.encode("utf-8")) + 1
            if current and current_len + added_len > MAX_MEMO_BYTES:
                batches.append(current)
                current = []
                current_len = header_len
            current.append(idx)
            current_len += added_len
        if current:
            batches.append(current)
    else:
        batches = [[i] for i in range(len(results))]

    memos = []
    for batch in batches:
        body = "\n".join(lines[i] for i in batch)
        memos.append(f"{memo_prefix}\n{body}" if memo_prefix else body)

    if dry_run:
        for i, memo in enumerate(memos, 1):
            click.echo(f"--- memo {i}/{len(memos)} ({len(memo.encode('utf-8'))} bytes, {len(batches[i - 1])} file(s)) ---")
            click.echo(memo)
        return

    kp = load_keypair(keypair)
    resolved_rpc_url = resolve_rpc_url(cluster, rpc_url)
    resolved_cluster = cluster if cluster and not rpc_url else None
    client = SolanaPoEClient(
        rpc_url=resolved_rpc_url,
        keypair=kp,
        memo_program_id=_memo_program_id(memo_program),
    )

    entries = []
    for batch, memo in zip(batches, memos):
        click.echo(f"submitting memo covering {len(batch)} file(s)...")
        receipt = client.send_memo(memo)
        click.echo(f"  signature: {receipt.signature}")
        for i in batch:
            r = results[i]
            entries.append(
                ManifestEntry(
                    full_path=r.full_path,
                    algorithm=r.algorithm,
                    hash=r.digest,
                    size=r.size,
                    signature=receipt.signature,
                    slot=receipt.slot,
                    block_time=receipt.block_time,
                    cluster=resolved_cluster,
                    rpc_url=resolved_rpc_url,
                )
            )

    write_manifest(entries, manifest_path)
    click.echo(f"wrote manifest with {len(entries)} entries to {manifest_path}")


@main.command("verify")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--check-files/--no-check-files",
    default=False,
    show_default=True,
    help=(
        "Also recompute each file's hash and compare it to the manifest. "
        "Each entry records the file's full filesystem path from when "
        "'submit' ran, and reads/re-hashes directly from that path -- the "
        "file must still exist there (or at the same path on this machine) "
        "for the check to run."
    ),
)
@click.option("--memo-program", type=click.Choice(sorted(MEMO_PROGRAM_IDS)), default="v2", show_default=True)
def verify_cmd(manifest_path: Path, check_files: bool, memo_program: str) -> None:
    """Re-fetch each manifest entry's transaction and confirm its memo matches the recorded hash."""
    entries = read_manifest(manifest_path)
    program_id = _memo_program_id(memo_program)
    clients: Dict[str, SolanaPoEClient] = {}
    memo_cache: Dict[str, Optional[str]] = {}
    all_ok = True

    for entry in entries:
        expected_line = f"{entry.algorithm}:{entry.hash}:{entry.full_path}"
        chain_status = "SKIPPED (no signature)"

        if entry.signature:
            rpc_url = entry.rpc_url or resolve_rpc_url(entry.cluster)
            if rpc_url not in clients:
                clients[rpc_url] = SolanaPoEClient(rpc_url=rpc_url, memo_program_id=program_id)
            if entry.signature not in memo_cache:
                memo_cache[entry.signature] = clients[rpc_url].fetch_memo(entry.signature)
            memo = memo_cache[entry.signature]

            if memo is None:
                chain_status = "FAIL (transaction or memo not found)"
                all_ok = False
            elif expected_line in memo.splitlines():
                chain_status = "OK"
            else:
                chain_status = "FAIL (hash not present in on-chain memo)"
                all_ok = False

        file_status = ""
        if check_files:
            local_path = Path(entry.full_path)
            if not local_path.is_file():
                file_status = " | file: MISSING"
                all_ok = False
            else:
                actual = hash_file(local_path, entry.algorithm, salt=entry.full_path)
                if actual == entry.hash:
                    file_status = " | file: OK"
                else:
                    file_status = " | file: MISMATCH"
                    all_ok = False

        click.echo(f"{entry.full_path}: chain={chain_status}{file_status}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
