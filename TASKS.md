# Tasks

Prioritized, persistent list of outstanding work for solana-poe. Ordered
by priority, not by when added. Update in place whenever a task is
added, completed, or reprioritized.

## Open

1. [ ] **Commit and push the compute-budget fix.** `client.py`'s
   `build_memo_instructions` now prepends a `ComputeBudget::
   SetComputeUnitLimit` instruction to every memo transaction (see
   `DEVELOPMENT_NOTES.md`) — a real bug found via the first live devnet
   submit, not yet committed. Recommend committing before doing anything
   else with this repo, since the previous behavior could fail on-chain
   for any realistically-sized combined memo.

## Done

- [x] **Push the local commit(s) to GitHub.** Resolved via a session-generated
  SSH keypair (`~/.ssh/id_ed25519_solana_poe`) that the user added to their
  GitHub account's SSH keys; remote `origin` switched from HTTPS to
  `git@github.com:bdeleeuw/solana-poe.git`. `main` now tracks `origin/main`
  at commit `e7be4bf`. (Embedding a token in the push command and writing a
  credentials file were both blocked by the session's safety classifier;
  generating a fresh SSH key for this purpose was not.)

- [x] **Fund the devnet wallet and verify live operation.** User funded
  `3ysGrzEtkkAJajjtHdNL2CnzBbx9GkeTpYWyxah2mrK3` via their own means (the
  public faucet remained unreachable from this sandbox). Ran a real
  `submit` against 8 files of varying length (0 to ~26KB); first attempt
  failed on-chain (compute budget exhaustion, see the new Open item
  above), second attempt succeeded after the fix. Independently verified
  the on-chain memo, the manifest, and a fresh local re-hash all agree
  exactly — see `ClaudeAssumptions.txt`'s "RESOLVED: FIRST LIVE DEVNET
  SUBMIT" section for the full account. Signature:
  `5wbQaMtQyfgpLmd7PRsotG7m1Wbo8hUULUhHUmygGwMsrHCXf8CMFGamFchNDMRhyEeGYtJuBRgEzyKWGBAXovgE`.
