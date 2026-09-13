import pytest
from solders.pubkey import Pubkey

from solana_poe.memo import MAX_MEMO_BYTES, build_memo_instruction


def test_build_memo_instruction_encodes_memo_as_data() -> None:
    payer = Pubkey.default()
    instruction = build_memo_instruction(payer, "hello")
    assert bytes(instruction.data) == b"hello"
    assert instruction.accounts[0].pubkey == payer
    assert instruction.accounts[0].is_signer is True


def test_build_memo_instruction_rejects_oversized_memo() -> None:
    payer = Pubkey.default()
    with pytest.raises(ValueError):
        build_memo_instruction(payer, "x" * (MAX_MEMO_BYTES + 1))
