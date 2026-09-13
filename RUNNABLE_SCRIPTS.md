# Runnable commands

This project has no `scripts/` directory — everything runs through the
packaged `solana-poe` CLI (`src/solana_poe/cli.py`, installed via the
`solana-poe` console-script entry point in `pyproject.toml`). This doc
plays the same role the global convention gives `scripts/`: what each
command does, its arguments, and caveats that don't show up in `--help`.
Keep this in sync with `cli.py` whenever a command or option changes.

## `solana-poe hash DIRECTORY`

Hashes every file under `DIRECTORY` and prints (or writes) JSON. No
network access, no keypair needed — this is the only command with zero
blockchain interaction.

- `--algo` (default `sha256`) — any `hashlib`-supported algorithm name.
- `--recursive/--no-recursive` (default recursive) — walk subdirectories
  or not.
- `--output PATH` — write JSON to a file instead of stdout.

**Caveat:** the `full_path` in the output is each file's *resolved*
absolute path (symlinks followed), not necessarily the path you typed on
the command line — see `ARCHITECTURE.md`'s salting section. This is also
what gets salted into the digest, so re-running from a different
directory with a relative `DIRECTORY` argument does **not** change the
digest (the resolved path is the same); only actually moving the file
does.

## `solana-poe submit DIRECTORY --keypair PATH [options]`

Hashes every file, builds one Memo transaction per file (or batched, see
`--combine`), signs and sends each with the given keypair, and writes a
JSON manifest.

- `--keypair PATH` (required) — Solana CLI JSON keypair file; pays fees
  and signs.
- `--cluster {devnet,testnet,mainnet-beta,localnet}` (default `devnet`)
  — ignored if `--rpc-url` is given.
- `--rpc-url URL` — overrides `--cluster`.
- `--algo`, `--recursive/--no-recursive` — same as `hash`.
- `--combine/--no-combine` (default: one transaction per file) — when
  set, packs as many raw hash values (space-separated) as fit under
  `MAX_MEMO_BYTES` (566 bytes, a conservative estimate — see
  `memo.py`) into each transaction, rather than one hash per
  transaction. Batch boundaries are determined by encoded byte length,
  not file count, so batch sizes vary. The memo itself contains only
  hash values — no algorithm, no path; those live in the manifest only.
- `--memo-prefix` (default `solana-poe:v1`) — first line of every memo;
  pass `""` (empty) to omit it entirely. Since it's counted against the
  same `MAX_MEMO_BYTES` ceiling as the hashes, an unreasonably long
  prefix can make `submit` refuse to send anything (see the oversized-hash
  caveat below).
- `--memo-program {v1,v2}` (default `v2`) — which Memo program id to
  target. `v2` is the current/maintained program.
- `--manifest PATH` (default `./solana-poe-manifest.json`) — where the
  receipt manifest is written. **Overwritten**, not appended, on every
  run — re-running `submit` on the same directory with the same
  `--manifest` path discards the previous manifest's receipts unless you
  pass a different path.
- `--dry-run` — hashes files and prints the exact memo text/byte counts
  that would be sent, but does not touch the network or require a valid
  keypair balance. Useful for previewing `--combine` batching.

**Caveats:**
- `submit` currently has no confirmed live devnet run — the public
  devnet airdrop faucet was unreachable from the development sandbox on
  every attempt (see `DEVELOPMENT_NOTES.md`). The transaction-building
  and signing path has only been exercised via `--dry-run` and an
  offline wire-format round-trip test, not against a real, funded
  submission.
- Every hash is checked against `MAX_MEMO_BYTES` *before* any batching
  or network activity, so an oversized hash (in practice, only reachable
  via an excessively long `--memo-prefix`, since real hash algorithms'
  digests are always well under the limit) aborts the whole run up
  front with a clear error — nothing gets partially submitted.

## `solana-poe verify MANIFEST_PATH [options]`

Re-fetches each manifest entry's transaction from the chain and checks
whether the entry's `hash` appears as one of the on-chain memo's
whitespace-separated tokens (exact match, not a substring check).

- `--check-files/--no-check-files` (default off) — additionally re-reads
  and re-hashes each file directly from its manifest-recorded
  `full_path` (using that same path as the salt) and compares to the
  recorded hash. Reports `MISSING` if the file no longer exists at that
  exact absolute path.
- `--memo-program {v1,v2}` (default `v2`) — must match whichever program
  id `submit` used, or every entry will report a chain FAIL.

**Caveats:**
- Exits `1` if any entry fails or is missing; `0` only if every entry
  passes. Useful as a CI/script gate.
- Can only verify legacy (non-versioned) transactions; if a transaction
  used an address lookup table, the memo read comes back as "not found"
  regardless of what it actually contains (see `ARCHITECTURE.md`).
- `--check-files` only works on the same machine (or an identical
  absolute path) the manifest was created on — there's no way to verify
  against a relocated copy of the directory. This is a known limitation,
  not a bug; see `ClaudeAssumptions.txt` item 27.
