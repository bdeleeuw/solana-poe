# Architecture

## Purpose

`solana-poe` hashes every file in a directory and anchors those hashes on
the Solana blockchain as a timestamped proof-of-existence, using the SPL
Memo program. No custom on-chain program is deployed — each Memo
transaction *is* the proof, and the transaction's block time is the
trustless timestamp. A JSON manifest ties local files to the transaction
signatures that anchored them, so a claim can be checked later.

## Scope

- A library (`solana_poe`) plus a thin `click`-based CLI (`solana-poe`)
  wrapping it.
- Three CLI verbs: `hash` (local only, no chain), `submit` (hash + post
  Memo transactions + write a manifest), `verify` (re-fetch transactions
  from chain and optionally re-hash local files against the manifest).
- Out of scope: any custom on-chain program, batching hashes into a
  Merkle tree, wallet/key management beyond loading a Solana CLI JSON
  keypair file, and any UI beyond the CLI.

## High-level design decisions

**Hashing is salted with the file's full absolute path.**
`hash_directory()` resolves each file to its canonical absolute path
(`Path.resolve()`) and folds that string into the digest:
`sha256(full_path_utf8 + b"\x00" + file_bytes)`. Two files with identical
bytes at different locations get different digests; moving a file changes
its digest even if content is untouched. This was an explicit, deliberate
choice (not just "hash the content") — see `ClaudeAssumptions.txt` for
the request history. One consequence: `verify --check-files` can only
re-hash a file that still exists at the exact absolute path recorded in
the manifest — there is currently no supported way to verify against a
relocated copy of a directory tree.

**`full_path` is the hash salt and the manifest's record of location; the
on-chain memo carries neither it nor the algorithm.** Earlier the memo
text embedded `algorithm:hash:full_path` per file; it now carries only
the raw hex digest(s), space-separated. `full_path` and `algorithm` are
salted into/associated with the hash and recorded in the manifest, but
deliberately not repeated on-chain. Trade-off: memos are far smaller
(letting the default combined mode pack many more files per
transaction), but the on-chain data alone no longer identifies which
file, path, or algorithm produced a given hash — `verify` (and anyone
else) needs the manifest for that, not just a block explorer.

**The RPC client wraps solana-py's async API in `asyncio.run()`.**
solana-py dropped its synchronous `Client`/`Transaction` API somewhere
around 0.40 in favor of an async-only `AsyncClient`. Rather than making
the whole library async (which would leak into the CLI and every
library caller), `SolanaPoEClient` in `client.py` keeps a synchronous
public surface (`send_memo`, `fetch_memo`) and runs each call to
completion internally with `asyncio.run()`. This means each call opens
and tears down its own `AsyncClient`/HTTP connection — fine for a CLI
tool submitting a handful of transactions, not optimized for
high-throughput use.

**Memo transactions are always legacy (non-versioned).**
`Transaction.new_signed_with_payer` builds a plain legacy transaction,
never a v0/address-lookup-table transaction. `fetch_memo` correspondingly
refuses to parse any transaction that used an address lookup table
(returns `None`, i.e. "unverifiable"), since it doesn't resolve ALT
accounts. This is fine for memos this tool created; a memo posted by some
other tool using an ALT-based transaction will not verify here.

**Every memo transaction includes an explicit compute-budget bump.**
`client.build_memo_instructions` always prepends a
`ComputeBudget::SetComputeUnitLimit` instruction (300,000 CU) ahead of
the memo instruction. Discovered via the first real devnet send: the
Memo program's cost scales with memo length (dominated by logging), and
Solana's default 200,000 CU budget is exhausted well before
`MAX_MEMO_BYTES`'s 566-byte wire-size ceiling is reached (measured
failure at 533 bytes). See `DEVELOPMENT_NOTES.md` for the full
bisection. `MAX_MEMO_BYTES` itself is unchanged — it still reflects the
transaction wire-size limit — but without this compute bump, a
transaction can be wire-size-valid and still fail on-chain.

**Batched transactions by default; `--individual` opts into one-per-file.**
By default `submit` packs as many raw hash values (space-separated) as
fit under a conservative per-memo byte ceiling (`MAX_MEMO_BYTES` in
`memo.py`) into each transaction, minimizing fee cost. `--individual`
reverts to a strict 1:1 mapping between files and transactions instead.
Either way, `submit` checks every hash fits under that ceiling *before*
batching or sending anything, so a value that can't fit even alone
aborts the whole run with nothing submitted, rather than partially
submitting and crashing mid-batch.

**Default cluster is devnet, not mainnet-beta.** A bare `submit` cannot
accidentally spend real SOL; mainnet requires an explicit
`--cluster mainnet-beta`.

## Module map

- `hashing.py` — file/directory hashing, salting.
- `memo.py` — builds the Memo-program instruction; holds the v1/v2
  program ids and the memo size ceiling.
- `client.py` — `SolanaPoEClient` (send/fetch memos), cluster URL
  resolution, keypair loading.
- `manifest.py` — `ManifestEntry` dataclass, JSON read/write.
- `cli.py` — the `hash`/`submit`/`verify` commands; the only place that
  ties hashing, the client, and the manifest together.

## Non-goals / known limitations

See `ClaudeAssumptions.txt` for the full list of design assumptions (most
are still standing and unconfirmed by the user) and
`DEVELOPMENT_NOTES.md` for concrete technical pitfalls hit while building
this. Headline limitations: no live devnet `submit` has ever been
executed end-to-end (public faucet was unreachable from the dev sandbox);
`verify` cannot check a relocated copy of a directory tree; no retry/
backoff around RPC rate limiting.
