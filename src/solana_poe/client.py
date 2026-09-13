from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment, Confirmed
from solana.rpc.models import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

from .memo import MEMO_PROGRAM_ID_V2, build_memo_instruction

CLUSTER_URLS = {
    "mainnet-beta": "https://api.mainnet-beta.solana.com",
    "testnet": "https://api.testnet.solana.com",
    "devnet": "https://api.devnet.solana.com",
    "localnet": "http://127.0.0.1:8899",
}
DEFAULT_CLUSTER = "devnet"


def resolve_rpc_url(cluster: Optional[str] = None, rpc_url: Optional[str] = None) -> str:
    """Turn a cluster name and/or explicit URL into a concrete RPC endpoint."""
    if rpc_url:
        return rpc_url
    cluster = cluster or DEFAULT_CLUSTER
    try:
        return CLUSTER_URLS[cluster]
    except KeyError as exc:
        raise ValueError(
            f"unknown cluster {cluster!r}, expected one of {sorted(CLUSTER_URLS)}"
        ) from exc


def load_keypair(path: Path) -> Keypair:
    """Load a Solana CLI-style JSON keypair file (a JSON array of 64 byte values)."""
    raw = json.loads(Path(path).expanduser().read_text())
    return Keypair.from_bytes(bytes(raw))


@dataclass(frozen=True)
class MemoReceipt:
    signature: str
    slot: Optional[int]
    block_time: Optional[int]
    memo: str


class SolanaPoEClient:
    """Synchronous wrapper around solana-py's AsyncClient for sending and
    reading Memo transactions. solana-py ships an async-only RPC client;
    this class runs each call to completion with `asyncio.run` so the
    library and CLI can stay synchronous.
    """

    def __init__(
        self,
        rpc_url: str,
        keypair: Optional[Keypair] = None,
        commitment: Commitment = Confirmed,
        memo_program_id: Pubkey = MEMO_PROGRAM_ID_V2,
    ) -> None:
        self.rpc_url = rpc_url
        self.keypair = keypair
        self.commitment = commitment
        self.memo_program_id = memo_program_id

    def send_memo(self, memo: str, max_retries: int = 3) -> MemoReceipt:
        """Sign and submit a single Memo transaction, waiting for confirmation."""
        if self.keypair is None:
            raise ValueError("a keypair is required to send transactions")
        return asyncio.run(self._send_memo(memo, max_retries))

    async def _send_memo(self, memo: str, max_retries: int) -> MemoReceipt:
        instruction = build_memo_instruction(
            self.keypair.pubkey(), memo, program_id=self.memo_program_id
        )
        async with AsyncClient(self.rpc_url, commitment=self.commitment) as client:
            recent_blockhash = (
                await client.get_latest_blockhash(commitment=self.commitment)
            ).value.blockhash

            tx = Transaction.new_signed_with_payer(
                [instruction],
                self.keypair.pubkey(),
                [self.keypair],
                recent_blockhash,
            )

            send_resp = await client.send_raw_transaction(
                bytes(tx),
                opts=TxOpts(
                    skip_confirmation=False,
                    skip_preflight=False,
                    preflight_commitment=self.commitment,
                    max_retries=max_retries,
                ),
            )
            signature = send_resp.value

            slot = None
            block_time = None
            tx_resp = await client.get_transaction(
                signature,
                commitment=self.commitment,
                max_supported_transaction_version=0,
            )
            if tx_resp.value is not None:
                slot = tx_resp.value.slot
                block_time = tx_resp.value.block_time

        return MemoReceipt(
            signature=str(signature), slot=slot, block_time=block_time, memo=memo
        )

    def fetch_memo(self, signature: str) -> Optional[str]:
        """Best-effort read of the memo text carried by a confirmed transaction.

        Returns None if the transaction cannot be found, `signature` isn't
        a validly-formatted signature at all, or the transaction carries
        no instruction for this client's memo program id.
        """
        return asyncio.run(self._fetch_memo(signature))

    async def _fetch_memo(self, signature: str) -> Optional[str]:
        try:
            parsed_signature = Signature.from_string(signature)
        except ValueError:
            return None
        async with AsyncClient(self.rpc_url, commitment=self.commitment) as client:
            tx_resp = await client.get_transaction(
                parsed_signature,
                encoding="base64",
                commitment=self.commitment,
                max_supported_transaction_version=0,
            )
        if tx_resp.value is None:
            return None

        message = tx_resp.value.transaction.transaction.message
        return extract_memo(message, self.memo_program_id)


def extract_memo(message, memo_program_id: Pubkey) -> Optional[str]:
    """Pull the memo text out of a decoded transaction message, if present.

    `message` is a solders `Message` or `MessageV0` (as returned by
    `VersionedTransaction.message` / a base64-encoded `get_transaction`
    response). Returns None if no instruction targets `memo_program_id`,
    or if the message relies on an address lookup table, since account
    indices could then point past the static `account_keys` list into
    accounts this function does not resolve.
    """
    if getattr(message, "address_table_lookups", None):
        return None
    account_keys = message.account_keys
    for instruction in message.instructions:
        program_id = account_keys[instruction.program_id_index]
        if program_id == memo_program_id:
            try:
                return bytes(instruction.data).decode("utf-8")
            except (UnicodeDecodeError, TypeError):
                return None
    return None
