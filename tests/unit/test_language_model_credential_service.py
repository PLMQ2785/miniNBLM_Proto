import stat

import pytest
from cryptography.fernet import Fernet

from app.services.language_model_credential_service import (
    LanguageModelCredentialCipher,
    LanguageModelCredentialError,
    LanguageModelMasterKeyError,
)


def test_initialize_creates_private_master_key_when_no_ciphertext_exists(tmp_path) -> None:
    """암호문이 없으면 master key를 자동 생성하고 0600 권한으로 보호한다."""
    key_file = tmp_path / "master.key"
    cipher = LanguageModelCredentialCipher(key_file)

    cipher.initialize(encrypted_credentials_exist=False)

    assert key_file.exists()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert key_file.read_bytes().strip()


def test_initialize_missing_master_key_with_ciphertext_fails_closed(tmp_path) -> None:
    """암호문이 남은 상태에서 master key가 없으면 생성하지 않고 실패한다."""
    key_file = tmp_path / "master.key"
    cipher = LanguageModelCredentialCipher(key_file)

    with pytest.raises(LanguageModelMasterKeyError, match="master key is missing"):
        cipher.initialize(encrypted_credentials_exist=True)

    assert not key_file.exists()


def test_encrypt_decrypt_round_trip(tmp_path) -> None:
    """Fernet 암호화와 복호화가 같은 credential을 복원한다."""
    key_file = tmp_path / "master.key"
    writer = LanguageModelCredentialCipher(key_file)
    ciphertext = writer.encrypt("test-credential")

    reader = LanguageModelCredentialCipher(key_file)

    assert reader.decrypt(ciphertext) == "test-credential"
    assert ciphertext != "test-credential"


def test_invalid_master_key_fails_closed(tmp_path) -> None:
    """손상된 master key는 credential 처리 전에 거부한다."""
    key_file = tmp_path / "master.key"
    key_file.write_bytes(b"not-a-fernet-key\n")

    with pytest.raises(LanguageModelMasterKeyError, match="master key is invalid"):
        LanguageModelCredentialCipher(key_file).initialize(encrypted_credentials_exist=True)


def test_wrong_master_key_fails_closed(tmp_path) -> None:
    """다른 master key로는 기존 암호문을 복호화할 수 없다."""
    key_file = tmp_path / "master.key"
    writer = LanguageModelCredentialCipher(key_file)
    ciphertext = writer.encrypt("test-credential")
    key_file.write_bytes(Fernet.generate_key() + b"\n")

    with pytest.raises(LanguageModelCredentialError, match="Cannot decrypt"):
        LanguageModelCredentialCipher(key_file).decrypt(ciphertext)


def test_invalid_ciphertext_fails_closed(tmp_path) -> None:
    """손상된 endpoint 암호문은 credential 오류로 처리한다."""
    cipher = LanguageModelCredentialCipher(tmp_path / "master.key")
    cipher.encrypt("test-credential")

    with pytest.raises(LanguageModelCredentialError, match="Cannot decrypt"):
        cipher.decrypt("not-a-fernet-token")
