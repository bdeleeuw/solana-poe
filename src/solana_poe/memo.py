from __future__ import annotations

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

# Current (v2) and legacy (v1) SPL Memo program ids.
MEMO_PROGRAM_ID_V2 = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
MEMO_PROGRAM_ID_V1 = Pubkey.from_string("Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo")

# Conservative ceiling on memo payload size that keeps a single memo
# instruction, one signer, and transaction overhead under Solana's
# 1232-byte transaction size limit.
MAX_MEMO_BYTES = 566


def build_memo_instruction(
    payer: Pubkey, memo: str, program_id: Pubkey = MEMO_PROGRAM_ID_V2
) -> Instruction:
    """Build a Memo-program instruction carrying `memo` as its data."""
    data = memo.encode("utf-8")
    if len(data) > MAX_MEMO_BYTES:
        raise ValueError(
            f"memo is {len(data)} bytes, exceeds the {MAX_MEMO_BYTES}-byte "
            "safety limit for a single transaction"
        )
    return Instruction(
        program_id=program_id,
        data=data,
        accounts=[AccountMeta(pubkey=payer, is_signer=True, is_writable=True)],
    )
