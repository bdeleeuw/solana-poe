from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction, VersionedTransaction

from solders.compute_budget import ID as COMPUTE_BUDGET_PROGRAM_ID

from solana_poe.client import (
    DEFAULT_COMPUTE_UNIT_LIMIT,
    SolanaPoEClient,
    build_memo_instructions,
    extract_memo,
)
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


def test_build_memo_instructions_includes_a_compute_budget_bump() -> None:
    # Regression test: a real devnet send failed with "exceeded CUs meter"
    # (ProgramFailedToComplete) around 533 bytes under Solana's default
    # 200,000 CU budget, well under MAX_MEMO_BYTES's 566-byte ceiling.
    # Every memo transaction must request a higher compute budget.
    kp = Keypair()
    instructions = build_memo_instructions(kp.pubkey(), "sha256:deadbeef:a.txt")

    assert len(instructions) == 2
    cu_ix, memo_ix = instructions
    assert cu_ix.program_id == COMPUTE_BUDGET_PROGRAM_ID
    assert memo_ix.program_id == MEMO_PROGRAM_ID_V2

    # The transaction must actually be buildable/signable with these
    # instructions (exercises the same construction path send_memo uses).
    tx = Transaction.new_signed_with_payer(
        instructions, kp.pubkey(), [kp], Hash.default()
    )
    assert len(bytes(tx)) > 0


def test_build_memo_instructions_uses_default_compute_unit_limit() -> None:
    payer = Keypair().pubkey()
    cu_ix, _ = build_memo_instructions(payer, "hello")
    # set_compute_unit_limit's encoded instruction data is a 1-byte
    # discriminator followed by the little-endian u32 unit count.
    encoded_limit = int.from_bytes(bytes(cu_ix.data)[1:5], "little")
    assert encoded_limit == DEFAULT_COMPUTE_UNIT_LIMIT
