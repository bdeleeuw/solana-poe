from pathlib import Path

from click.testing import CliRunner

from solana_poe.client import SolanaPoEClient
from solana_poe.cli import main
from solana_poe.memo import MAX_MEMO_BYTES


def _manifest_json(hash_value: str) -> str:
    # `signature` just needs to be truthy -- fetch_memo is monkeypatched in
    # the tests that use this, so its contents are never actually parsed.
    return (
        '[{"full_path": "/tmp/x.txt", "algorithm": "sha256", "hash": "%s", '
        '"size": 1, "signature": "placeholder-signature", '
        '"slot": null, "block_time": null, "cluster": "devnet", '
        '"rpc_url": "https://api.devnet.solana.com"}]' % hash_value
    )


def _assert_clean_failure(result) -> None:
    """A CLI error should exit 1 via sys.exit, not leak a raw traceback."""
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output


def test_hash_rejects_bogus_algorithm(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi")
    result = CliRunner().invoke(main, ["hash", str(tmp_path), "--algo", "not-a-real-algo"])
    _assert_clean_failure(result)
    assert "unsupported hash type" in result.output


def test_hash_rejects_empty_string_path_instead_of_using_cwd(monkeypatch, tmp_path: Path) -> None:
    # Regression test for a real bug found by adversarial QA: an empty
    # string spec (e.g. from an unset shell variable interpolated into
    # the command line) must not silently fall back to "every file under
    # the current directory."
    (tmp_path / "a.txt").write_text("hi")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["hash", ""])
    _assert_clean_failure(result)
    assert "empty path specification" in result.output


def test_hash_on_an_empty_directory_succeeds_with_no_results(tmp_path: Path) -> None:
    # Documented, intentional asymmetry with `submit` (see the next test):
    # `hash` is purely observational, so "nothing here" is valid output,
    # not an error.
    result = CliRunner().invoke(main, ["hash", str(tmp_path)])
    assert result.exit_code == 0
    assert result.output.strip() == "[]"


def test_submit_on_an_empty_directory_errors_instead_of_submitting_nothing(
    tmp_path: Path, tmp_path_factory
) -> None:
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")
    result = CliRunner().invoke(
        main, ["submit", str(tmp_path), "--keypair", str(keypair), "--dry-run"]
    )
    _assert_clean_failure(result)
    assert "no files found" in result.output


def test_submit_rejects_bogus_algorithm(tmp_path: Path, tmp_path_factory) -> None:
    (tmp_path / "a.txt").write_text("hi")
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")
    result = CliRunner().invoke(
        main,
        ["submit", str(tmp_path), "--keypair", str(keypair), "--algo", "not-a-real-algo", "--dry-run"],
    )
    _assert_clean_failure(result)
    assert "unsupported hash type" in result.output


def test_submit_dry_run_rejects_prefix_too_long_for_any_memo(tmp_path: Path, tmp_path_factory) -> None:
    # File paths no longer appear in the memo (only raw hash values do), so
    # a long path can't make a memo line oversized any more -- the only
    # remaining way to trigger this safety net is a huge --memo-prefix.
    (tmp_path / "a.txt").write_text("hi")
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")

    huge_prefix = "x" * (MAX_MEMO_BYTES + 10)
    result = CliRunner().invoke(
        main,
        ["submit", str(tmp_path), "--keypair", str(keypair), "--memo-prefix", huge_prefix, "--dry-run"],
    )
    _assert_clean_failure(result)
    assert f"limit {MAX_MEMO_BYTES} bytes" in result.output
    assert "Nothing was submitted" in result.output


def test_submit_dry_run_memo_is_just_the_hash_no_path_or_algorithm(tmp_path: Path, tmp_path_factory) -> None:
    (tmp_path / "a.txt").write_text("hello world")
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")

    result = CliRunner().invoke(
        main, ["submit", str(tmp_path), "--keypair", str(keypair), "--memo-prefix", "", "--dry-run"]
    )
    assert result.exit_code == 0, result.output

    from solana_poe.hashing import hash_file

    expected_digest = hash_file(tmp_path / "a.txt", salt=str((tmp_path / "a.txt").resolve()))
    lines = [line for line in result.output.splitlines() if line.strip()]
    memo_body = lines[-1]
    assert memo_body == expected_digest
    assert str(tmp_path) not in memo_body
    assert ":" not in memo_body


def test_submit_dry_run_default_combines_multiple_hashes_into_one_memo(tmp_path: Path, tmp_path_factory) -> None:
    # Combining is the default now -- no --combine flag needed.
    (tmp_path / "a.txt").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")

    result = CliRunner().invoke(
        main,
        ["submit", str(tmp_path), "--keypair", str(keypair), "--memo-prefix", "", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "memo 1/1" in result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    memo_body = lines[-1]
    tokens = memo_body.split(" ")
    assert len(tokens) == 2
    assert all(len(t) == 64 for t in tokens)  # sha256 hex digests


def test_submit_dry_run_individual_flag_sends_one_memo_per_file(tmp_path: Path, tmp_path_factory) -> None:
    (tmp_path / "a.txt").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    keypair = tmp_path_factory.mktemp("kp") / "id.json"
    keypair.write_text("[]")

    result = CliRunner().invoke(
        main,
        ["submit", str(tmp_path), "--keypair", str(keypair), "--memo-prefix", "", "--individual", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "memo 1/2" in result.output
    assert "memo 2/2" in result.output
    memo_lines = [line for line in result.output.splitlines() if line.strip() and not line.startswith("---")]
    assert len(memo_lines) == 2
    for line in memo_lines:
        assert " " not in line
        assert len(line) == 64  # a lone sha256 hex digest, no other file's hash joined in


def test_verify_rejects_invalid_json_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("not json at all")
    result = CliRunner().invoke(main, ["verify", str(manifest)])
    _assert_clean_failure(result)
    assert "not valid JSON" in result.output


def test_verify_rejects_manifest_with_missing_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('[{"full_path": "/tmp/x", "hash": "abc"}]')
    result = CliRunner().invoke(main, ["verify", str(manifest)])
    _assert_clean_failure(result)
    assert "doesn't match the manifest schema" in result.output


def test_verify_handles_malformed_signature_without_crashing(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """
        [{
            "full_path": "/tmp/x", "algorithm": "sha256", "hash": "abc", "size": 1,
            "signature": "not-a-real-signature", "slot": null, "block_time": null,
            "cluster": "devnet", "rpc_url": "https://api.devnet.solana.com"
        }]
        """
    )
    result = CliRunner().invoke(main, ["verify", str(manifest)])
    # A malformed signature is a legitimate FAIL, but must not crash.
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "FAIL" in result.output


def test_verify_matches_hash_as_one_of_several_space_separated_tokens(tmp_path: Path, monkeypatch) -> None:
    target_hash = "b" * 64
    monkeypatch.setattr(
        SolanaPoEClient, "fetch_memo", lambda self, sig: f"{'a' * 64} {target_hash} {'c' * 64}"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(_manifest_json(target_hash))

    result = CliRunner().invoke(main, ["verify", str(manifest)])
    assert result.exit_code == 0, result.output
    assert "chain=OK" in result.output


def test_verify_does_not_match_hash_as_a_substring_of_another_token(tmp_path: Path, monkeypatch) -> None:
    # entry.hash is "bb"*32; the on-chain memo only has it as a prefix of a
    # longer token, which must NOT count as a match (exact-token only).
    target_hash = "b" * 64
    monkeypatch.setattr(
        SolanaPoEClient, "fetch_memo", lambda self, sig: target_hash + "extra-suffix-not-a-real-hash"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(_manifest_json(target_hash))

    result = CliRunner().invoke(main, ["verify", str(manifest)])
    assert result.exit_code == 1
    assert "FAIL (hash not present in on-chain memo)" in result.output
