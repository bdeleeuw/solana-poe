# solana-poe

Hash every file in a directory and anchor those hashes on Solana as a
timestamped proof-of-existence, using the SPL Memo program. No custom
on-chain program is required — each memo transaction is itself the proof,
and Solana's block time gives you a trustless timestamp.

## Install

```bash
cd solana-poe
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Usage

Hash a directory locally (no blockchain interaction):

```bash
solana-poe hash ./my-files
```

Post each file's hash to devnet as Memo transactions, packing as many
hashes as fit into as few transactions as possible by default, and record
the results in a manifest:

```bash
solana-poe submit ./my-files \
  --keypair ~/.config/solana/id.json \
  --cluster devnet \
  --manifest manifest.json
```

Send one transaction per file instead (more expensive, but a strict 1:1
mapping between files and transactions):

```bash
solana-poe submit ./my-files --keypair ~/.config/solana/id.json --individual
```

Preview the memos that would be sent without spending anything or touching
the network:

```bash
solana-poe submit ./my-files --keypair ~/.config/solana/id.json --dry-run
```

Verify a manifest later — re-fetches each transaction from the chain,
checks its memo contains the recorded hash, and optionally recomputes local
file hashes to confirm the files haven't changed:

```bash
solana-poe verify manifest.json --check-files
```

`verify` exits non-zero if any entry fails.

## Hash salting

Each file's digest is salted with that file's full, resolved, absolute
filesystem path:

```
digest = sha256(full_path.encode("utf-8") + b"\x00" + file_bytes)
```

So `solana-poe hash ./my-files` salts each digest with something like
`/home/alice/project/my-files/docs/report.pdf`, not just the file's
content or a path relative to anything. This means:

- Two files with identical bytes at different locations get different
  digests.
- Moving or renaming a file (even without touching its content) changes
  its digest, since the digest also binds the file's exact location.
- `verify --check-files` re-hashes each file directly from the full path
  recorded in the manifest, so the file must still exist at that same
  absolute path (typically: the same machine, unmoved) for the check to
  run; otherwise it reports MISSING.

## Memo format

Each memo contains just the raw hex digests, space-separated (one per
file the memo covers), optionally preceded by a `--memo-prefix` tag line
(default `solana-poe:v1`) on its own line above them:

```
solana-poe:v1
9c1185a5c5e9fc54612808977ee8f548b2258d31 4a7d1ed414474e4033ac29ccb8653d9b
```

The memo does **not** contain the algorithm or the file path — only the
manifest does (see below). This keeps memos small, letting the default
(combined) mode pack far more files per transaction than the old
`algo:hash:path`-per-line format could, at the cost of the on-chain data
no longer being self-describing: reading a transaction on a Solana
explorer tells you a hash was anchored at that block time, but not which
file, path, or algorithm produced it — you need the corresponding
manifest for that.

## Manifest format

`submit` writes a JSON array of entries:

```json
{
  "full_path": "/home/alice/project/my-files/docs/report.pdf",
  "algorithm": "sha256",
  "hash": "...",
  "size": 12345,
  "signature": "...",
  "slot": 123456789,
  "block_time": 1700000000,
  "cluster": "devnet",
  "rpc_url": "https://api.devnet.solana.com"
}
```

Keep this file — it's what lets you or anyone else later prove the file
existed (with that hash, at that exact path) at that block time.

## Library

The CLI is a thin wrapper over `solana_poe`:

```python
from pathlib import Path
from solana_poe import hash_directory, load_keypair, SolanaPoEClient

results = hash_directory(Path("./my-files"))
client = SolanaPoEClient(
    rpc_url="https://api.devnet.solana.com",
    keypair=load_keypair(Path("~/.config/solana/id.json")),
)
for r in results:
    # r.digest is already salted with r.full_path (the file's resolved,
    # absolute path); hash_file(path) alone, with no salt argument,
    # gives the unsalted content hash if you need that too. The memo
    # itself carries only the hash -- keep full_path/algorithm yourself
    # (e.g. in your own manifest) if you'll need them later.
    receipt = client.send_memo(r.digest)
    print(r.full_path, receipt.signature)
```

## Notes

- Fee payer needs SOL in the target cluster (use `solana airdrop` on
  devnet/testnet).
- A transaction's memo is limited to a few hundred bytes; by default
  `submit` packs as many hash values per transaction as fit under that
  limit (`--individual` opts out, one transaction per file instead). If
  even a single hash can't fit alone (e.g. an extremely long
  `--memo-prefix`), `submit` refuses to send anything rather than
  partially submitting.
- `--cluster` defaults to `devnet`. Use `--cluster mainnet-beta` (real SOL)
  or `--rpc-url` for a custom/private endpoint.
