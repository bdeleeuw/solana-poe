from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

import click

from .client import CLUSTER_URLS, SolanaPoEClient, load_keypair, resolve_rpc_url
from .hashing import DEFAULT_ALGORITHM, hash_file, hash_paths
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
@click.argument("paths", nargs=-1, required=True)
@click.option("--algo", default=DEFAULT_ALGORITHM, show_default=True, help="Hash algorithm (any hashlib name).")
@click.option("--recursive/--no-recursive", default=True, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), help="Write results as JSON to this file instead of stdout.")
def hash_cmd(paths: tuple, algo: str, recursive: bool, output: Optional[Path]) -> None:
    """Hash every file resolved from PATHS. No blockchain interaction.

    Each PATH may be a single file, a directory (every file under it is
    hashed), or a glob pattern like '*.txt' or 'data/**/*.pdf' (quote it
    if you don't want your shell to expand it first).
    """
    try:
        results = hash_paths(paths, algorithm=algo, recursive=recursive)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
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
@click.argument("paths", nargs=-1, required=True)
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
    "--individual",
    is_flag=True,
    default=False,
    show_default=True,
    help="Submit one transaction per file instead of the default: packing as many file hashes as fit into each memo.",
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
    paths: tuple,
    keypair: Path,
    cluster: Optional[str],
    rpc_url: Optional[str],
    algo: str,
    recursive: bool,
    individual: bool,
    memo_prefix: str,
    memo_program: str,
    manifest_path: Path,
    dry_run: bool,
) -> None:
    """Hash every file resolved from PATHS and post each hash to Solana as
    a Memo transaction.

    Each PATH may be a single file, a directory (every file under it is
    hashed), or a glob pattern like '*.txt' or 'data/**/*.pdf' (quote it
    if you don't want your shell to expand it first).
    """
    try:
        results = hash_paths(paths, algorithm=algo, recursive=recursive)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    if not results:
        click.echo("no files found", err=True)
        sys.exit(1)

    # Each memo carries only the raw hash values -- no algorithm, no path.
    # full_path/algorithm/hash are recorded in the manifest instead; see
    # ARCHITECTURE.md for the trade-off this implies for on-chain-only
    # verification.
    hashes = [r.digest for r in results]

    oversized = [
        results[i].full_path
        for i, h in enumerate(hashes)
        if len((f"{memo_prefix}\n{h}" if memo_prefix else h).encode("utf-8")) > MAX_MEMO_BYTES
    ]
    if oversized:
        click.echo(
            f"error: {len(oversized)} file hash(es) can't fit in a single memo "
            f"(limit {MAX_MEMO_BYTES} bytes including the memo prefix) even alone, "
            "so no combination of batching can send them. Nothing was submitted:",
            err=True,
        )
        for p in oversized:
            click.echo(f"  {p}", err=True)
        sys.exit(1)

    batches: list = []
    if individual:
        batches = [[i] for i in range(len(results))]
    else:
        header_len = len(memo_prefix.encode("utf-8")) + 1 if memo_prefix else 0
        current: list = []
        current_len = header_len
        for idx, h in enumerate(hashes):
            added_len = len(h.encode("utf-8")) + 1
            if current and current_len + added_len > MAX_MEMO_BYTES:
                batches.append(current)
                current = []
                current_len = header_len
            current.append(idx)
            current_len += added_len
        if current:
            batches.append(current)

    memos = []
    for batch in batches:
        body = " ".join(hashes[i] for i in batch)
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
    try:
        entries = read_manifest(manifest_path)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    program_id = _memo_program_id(memo_program)
    clients: Dict[str, SolanaPoEClient] = {}
    memo_cache: Dict[str, Optional[str]] = {}
    all_ok = True

    for entry in entries:
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
            elif entry.hash in memo.split():
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
                try:
                    actual = hash_file(local_path, entry.algorithm, salt=entry.full_path)
                except ValueError as exc:
                    file_status = f" | file: ERROR ({exc})"
                    all_ok = False
                else:
                    if actual == entry.hash:
                        file_status = " | file: OK"
                    else:
                        file_status = " | file: MISMATCH"
                        all_ok = False

        click.echo(f"{entry.full_path}: chain={chain_status}{file_status}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
