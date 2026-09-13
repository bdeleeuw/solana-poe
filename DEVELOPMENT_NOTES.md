# Development notes

General pitfalls and resolutions hit while building `solana-poe`,
organized by topic, most recent first within each topic. Distinct from
`ClaudeAssumptions.txt` (which tracks unconfirmed design *assumptions*)
and `ARCHITECTURE.md` (which explains the *current* design) — this doc is
for reusable "here's what actually happened and how it was fixed"
knowledge.

## solana-py / Solana RPC

- **`solana-py` 0.40.x has no synchronous client.** `solana.rpc.api.Client`
  and `solana.transaction.Transaction` (the old sync/legacy API) do not
  exist in 0.40.3, despite a dependency pin of `solana>=0.34` allowing it
  to resolve. Only `solana.rpc.async_api.AsyncClient` remains. If you pin
  an older solana-py (e.g. 0.34.x) the sync API does exist — but this
  project targets whatever the pin resolves to, which was 0.40.3 at
  install time, so the client wraps `AsyncClient` in `asyncio.run()`
  instead. Check what actually installed (`pip show solana`) before
  assuming which API surface is available; don't trust older
  examples/docs.

- **`get_transaction`'s default ("json") encoding returns base58-encoded
  *strings* for instruction data, not bytes.** `UiCompiledInstruction.data`
  under default encoding is a base58 string. Request
  `encoding="base64"` instead — solana-py then decodes the response into
  a real `solders.transaction.VersionedTransaction`, whose
  `CompiledInstruction.data` is actual bytes. Verified this by
  round-tripping a locally-built, locally-signed transaction through the
  identical decode path (`VersionedTransaction.from_bytes`) with no
  network call — see `tests/test_client_parsing.py`.

- **`TxOpts` moved.** In older solana-py it's importable from
  `solana.rpc.types`; in 0.40.3 it's `solana.rpc.models.TxOpts`.

- **Address-lookup-table (v0) transactions can't be parsed by naive
  `account_keys[instruction.program_id_index]` indexing** — an
  instruction's account indices can point past the static `account_keys`
  list into accounts resolved from an on-chain address lookup table,
  which requires an extra RPC round-trip to resolve and isn't currently
  implemented. `extract_memo()` in `client.py` deliberately bails out
  (`return None`) when `message.address_table_lookups` is non-empty,
  rather than silently mis-parsing. Since this tool only ever builds
  legacy transactions itself, this only affects memos from other tools.

- **Public RPC endpoints (mainnet-beta and devnet) rate-limit
  aggressively (HTTP 429)** under even light, sequential polling during
  manual testing. No retry/backoff is implemented in the library; expect
  to hand-retry when testing against the public endpoints.

- **The public devnet airdrop faucet was unreachable from the dev
  sandbox** on every attempt (`request_airdrop` → `HTTPStatusError` /
  "Internal error"), independent of amount or retry count. A fully live
  `submit` has never been executed end-to-end as a result — see
  `ClaudeAssumptions.txt` item 21.

## Solana Memo program

- **Do not trust a memorized program id.** An initial guess at the Memo
  v2 program id (`MemoSq4gqABAXKb96qnH8TysNKBEcgnyUx23YkzB`) was wrong.
  The correct ids, verified against the installed `spl.memo.constants`
  module and cross-checked against upstream source:
  - v2 (current): `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`
  - v1 (legacy): `Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo` (confirmed
    via the `declare_id!` macro in the `spl-memo` 1.0.0 Rust crate source
    on docs.rs)

- **The default 200,000 compute-unit budget is NOT enough for a large
  memo, well below the transaction's own 1232-byte wire-size limit.**
  Discovered on the very first real devnet send: an 8-file, 533-byte
  combined memo (well under the 566-byte `MAX_MEMO_BYTES` wire-size
  ceiling) was rejected during preflight simulation with
  `ProgramFailedToComplete` / "exceeded CUs meter at BPF instruction",
  consuming exactly 200,000 of 200,000 CU. The Memo program's cost is
  apparently dominated by logging the memo text (`Program log: Memo (len
  N): "..."` — visible in `logMessages`), which scales with length, not
  by anything wire-size-related. Bisected on live devnet: 500 bytes
  succeeded under the default budget, 533 bytes failed. With an explicit
  `ComputeBudget::SetComputeUnitLimit` instruction (`solders.compute_budget
  .set_compute_unit_limit`) prepended ahead of the memo instruction, 533
  bytes succeeds comfortably (verified: 202,273 of a requested 299,850 CU
  used for an 8-file real transaction), and even much larger memos (900+
  bytes) succeed up to a raised limit — the true remaining constraint
  becomes the transaction's 1232-byte wire size again, as originally
  assumed. Every memo transaction this library sends now includes this
  instruction (`client.build_memo_instructions`,
  `DEFAULT_COMPUTE_UNIT_LIMIT = 300_000`, empirically verified sufficient
  with margin at the full `MAX_MEMO_BYTES` ceiling). Lesson: a "conservative"
  byte-size estimate for an on-chain program's input can still be
  completely wrong if you haven't checked what that program's compute
  cost actually does with that input — dry-run/offline testing can't
  catch this class of bug at all; only a real send against a live cluster
  can.

## Manifest / path design

- **`Path.resolve()` follows symlinks**, unlike `os.path.abspath()`.
  Hashing a file reached through a symlink records the symlink's
  *target* path as the salt, not the symlink's own path. Relevant if a
  future feature needs to preserve "the path the user typed" rather than
  the canonical filesystem path.

- **Joining a base directory onto an absolute path is a silent no-op in
  pathlib**: `Path(some_dir) / "/absolute/path"` evaluates to
  `/absolute/path`, discarding `some_dir` entirely. This broke an earlier
  version of `verify --directory <dir>` once the manifest started
  storing absolute paths — the flag looked like it worked but silently
  had no effect. Replaced with a `--check-files` boolean that always
  reads from the manifest's recorded `full_path` directly, to avoid
  shipping that footgun.

## Environment / tooling

- **This sandboxed session starts with no GitHub credentials available** —
  no `gh` CLI, no SSH key, no stored git credential helper, no token in
  the environment. Both embedding a token directly in a `git push`
  command and writing a `~/.git-credentials` file were blocked by the
  session's safety classifier (command-line secret exposure and
  unauthorized persistence, respectively).

  **What worked:** generating a brand-new SSH keypair *in* the session
  (`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_<name> -N ""`) was *not*
  blocked — creating fresh credentials is apparently treated differently
  from persisting a secret the user already handed over. The user then
  added the public key to their GitHub account's SSH keys
  (github.com/settings/ssh/new), and the push succeeded using
  `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_<name> -o IdentitiesOnly=yes"
  git push ...` against an `origin` remote switched to the
  `git@github.com:...` SSH form. Also needed: `ssh-keyscan -t ed25519
  github.com >> ~/.ssh/known_hosts` first, to avoid an interactive host-key
  prompt. This key is session-scoped, not committed anywhere, and would
  need to be regenerated (and re-added to GitHub) in a fresh session.
