from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction, VersionedTransaction

from solana_poe.client import SolanaPoEClient, extract_memo
from solana_poe.memo import MEMO_PROGRAM_ID_V2, build_memo_instruction


def _build_and_decode(memo: str) -> object:
    """Sign a memo transaction locally, then decode it exactly the way
    `SolanaPoEClient.fetch_memo` decodes a base64-encoded RPC response:
    raw wire bytes -> `VersionedTransaction.from_bytes`.
    """
    kp = Keypair()
    instruction = build_memo_instruction(kp.pubkey(), memo)
    tx = Transaction.new_signed_with_payer(
        [instruction], kp.pubkey(), [kp], Hash.default()
    )
    decoded = VersionedTransaction.from_bytes(bytes(tx))
    return decoded.message


def test_extract_memo_round_trips_through_wire_format() -> None:
    message = _build_and_decode("sha256:deadbeef:a.txt")
    assert extract_memo(message, MEMO_PROGRAM_ID_V2) == "sha256:deadbeef:a.txt"


def test_extract_memo_returns_none_for_wrong_program_id() -> None:
    from solders.pubkey import Pubkey

    message = _build_and_decode("sha256:deadbeef:a.txt")
    assert extract_memo(message, Pubkey.default()) is None


def test_fetch_memo_returns_none_for_malformed_signature_without_network_call() -> None:
    # Signature.from_string() fails before any RPC call is attempted, so
    # this exercises the fix without needing network access.
    client = SolanaPoEClient(rpc_url="https://invalid.invalid")
    assert client.fetch_memo("not-a-real-signature") is None
