# Tasks

Prioritized, persistent list of outstanding work for solana-poe. Ordered
by priority, not by when added. Update in place whenever a task is
added, completed, or reprioritized.

## Open

1. [ ] **Fund the devnet wallet.** Address:
   `3ysGrzEtkkAJajjtHdNL2CnzBbx9GkeTpYWyxah2mrK3` (keypair file:
   `devnet-keypair.json`, gitignored — do not commit). The public devnet
   airdrop faucet was unreachable from the dev sandbox on every attempt
   (see `DEVELOPMENT_NOTES.md`). Needed to run `solana-poe submit`
   end-to-end against a live cluster for the first time — see
   `ClaudeAssumptions.txt` item 21.

2. [ ] **Push the local commit to GitHub.** Remote `origin` is already
   set to `https://github.com/bdeleeuw/solana-poe.git` and the initial
   commit (`e2af65b`, branch `master`) is ready to go. Blocked on
   credentials: this sandbox has no `gh` CLI, SSH key, or stored git
   credentials, and the session's safety classifier blocks both
   embedding a token in the push command and writing a credentials file
   to disk (see `DEVELOPMENT_NOTES.md`). Needs to be run from outside
   the sandbox, or with a user-approved auth method.

## Done

(none yet)
