import pytest


def test_normalize_email_is_stable_and_rejects_invalid_values() -> None:
    from app.services.accounts import normalize_email

    assert normalize_email("  User.Name@Example.COM ") == "user.name@example.com"
    for invalid in ("", "missing-at.example.com", "a@b", "two words@example.com"):
        with pytest.raises(ValueError, match="email"):
            normalize_email(invalid)


def test_scrypt_password_envelope_verifies_without_storing_plaintext() -> None:
    from app.services.accounts import hash_password, verify_password

    envelope = hash_password("correct horse battery staple")

    assert "correct horse" not in envelope
    assert envelope.startswith("scrypt$")
    assert verify_password("correct horse battery staple", envelope) is True
    assert verify_password("wrong password", envelope) is False
    assert verify_password("correct horse battery staple", "broken") is False


def test_account_tokens_are_random_and_only_the_hash_is_stable() -> None:
    from app.services.accounts import new_token, token_sha256

    first = new_token()
    second = new_token()

    assert first != second
    assert len(first) >= 32
    assert token_sha256(first) == token_sha256(first)
    assert token_sha256(first) != token_sha256(second)
