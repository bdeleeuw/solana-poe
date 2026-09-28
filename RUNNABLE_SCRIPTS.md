# Runnable commands

This project has no `scripts/` directory — everything runs through the
packaged `solana-poe` CLI (`src/solana_poe/cli.py`, installed via the
`solana-poe` console-script entry point in `pyproject.toml`). This doc
plays the same role the global convention gives `scripts/`: what each
command does, its arguments, and caveats that don't show up in `--help`.
Keep this in sync with `cli.py` whenever a command or option changes.

## `solana-poe hash PATHS...`

Hashes every file resolved from one or more `PATHS` and prints (or
writes) JSON. No network access, no keypair needed — this is the only
command with zero blockchain interaction.

Each `PATH` is resolved by `hashing.resolve_targets()` (shared with
`submit`):
- an existing file — hashed directly.
- an existing directory — every file under it (respecting
  `--recursive`).
- anything else — treated as a glob pattern (`*`, `?`, `[...]`, and `**`
  for recursive matching); quote it if you don't want your shell to
  expand it before the program sees it. A directory matched by a glob is
  itself expanded the same way a plain directory argument would be.

Multiple `PATHS` can be given and mixed freely (e.g. `a.txt ./dir
'*.pdf'`); results are deduplicated by resolved absolute path. A `PATH`
that doesn't exist and isn't a glob with any match is an error (exit 1)
— nothing is hashed if any one of the given paths can't be resolved
(including a single empty string, which is explicitly rejected rather
than silently treated as the current directory — see
`DEVELOPMENT_NOTES.md`).

- `--algo` (default `sha256`) — any `hashlib`-supported algorithm name.
- `--recursive/--no-recursive` (default recursive) — for any `PATH`
  that's (or matches) a directory, walk its subdirectories or not.
- `--output PATH` — write JSON to a file instead of stdout.

**Caveats:**
- the `full_path` in the output is each file's *resolved* absolute path
  (symlinks followed), not necessarily the path you typed on the
  command line — see `ARCHITECTURE.md`'s salting section. This is also
  what gets salted into the digest, so re-running from a different
  working directory with the same relative path arguments does **not**
  change the digest (the resolved path is the same); only actually
  moving the file does.
- a directory `PATH` picks up dotfiles; a glob `PATH` does not (standard
  shell/glob convention) — `hash somedir` and `hash 'somedir/*'` can
  return different file sets.
- an existing-but-empty directory `PATH` is not an error for `hash` —
  it succeeds and prints `[]` (contrast with `submit`, below).
- a symlinked *subdirectory* found while walking a directory is not
  followed (a symlink given directly as a `PATH` is).

## `solana-poe submit PATHS... --keypair PATH [options]`

Hashes every file, builds Memo transaction(s) (batched by default, or
one per file with `--individual`), signs and sends each with the given
keypair, and writes a JSON manifest.

- `--keypair PATH` (required) — Solana CLI JSON keypair file; pays fees
  and signs.
- `--cluster {devnet,testnet,mainnet-beta,localnet}` (default `devnet`)
  — ignored if `--rpc-url` is given.
- `--rpc-url URL` — overrides `--cluster`.
- `--algo`, `--recursive/--no-recursive` — same as `hash`.
- `--individual` (default off, i.e. batching is the default) — send one
  transaction per file instead of packing multiple hashes into each
  memo. Without it, `submit` packs as many raw hash values
  (space-separated) as fit under `MAX_MEMO_BYTES` (566 bytes, a
  conservative estimate — see `memo.py`) into each transaction. Batch
  boundaries are determined by encoded byte length, not file count, so
  batch sizes vary. The memo itself contains only hash values — no
  algorithm, no path; those live in the manifest only.
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
  keypair balance. Useful for previewing batching.

**Caveats:**
- `submit` has been verified against a real, funded devnet transaction
  exactly once (8 files, combined mode) — see `ClaudeAssumptions.txt`'s
  "RESOLVED: FIRST LIVE DEVNET SUBMIT" section. `--individual` mode and
  mainnet have not been exercised against a live network.
- An existing-but-empty `PATH` (e.g. an empty directory) makes `submit`
  refuse to send anything (`no files found`, exit 1) — unlike `hash`,
  which succeeds with `[]` for the same input. Intentional: submitting
  nothing isn't a useful action worth a network round trip.
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
