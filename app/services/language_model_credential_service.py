import os
import threading
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class LanguageModelMasterKeyError(Exception):
    """master key가 없거나 손상되어 credential을 안전하게 처리할 수 없음을 나타낸다."""


class LanguageModelCredentialError(Exception):
    """저장된 endpoint credential 암호문을 복호화할 수 없음을 나타낸다."""


class LanguageModelCredentialCipher:
    """자동 생성한 private master key로 JSON credential을 암·복호화한다."""

    def __init__(self, key_file: Path) -> None:
        self.key_file = key_file.expanduser()
        self._mutex = threading.Lock()
        self._fernet: Fernet | None = None
        self._key_signature: tuple[int, int, int] | None = None

    def initialize(self, *, encrypted_credentials_exist: bool) -> None:
        """key 교체를 감지하고 암호문이 없을 때만 최초 key를 생성한다."""
        with self._mutex:
            signature = self._signature()
            if self._fernet is not None and signature == self._key_signature:
                return
            if signature is None:
                if encrypted_credentials_exist:
                    raise LanguageModelMasterKeyError(
                        "LLM credential master key is missing while encrypted credentials exist"
                    )
                self._create_key()
                signature = self._signature()
            try:
                key = self.key_file.read_bytes().strip()
            except OSError as exc:
                raise LanguageModelMasterKeyError("Cannot read LLM credential master key") from exc
            try:
                fernet = Fernet(key)
            except (TypeError, ValueError) as exc:
                raise LanguageModelMasterKeyError("LLM credential master key is invalid") from exc
            self._fernet = fernet
            self._key_signature = signature

    def encrypt(self, value: str) -> str:
        """관리자가 입력한 credential을 JSON 저장용 Fernet token으로 바꾼다."""
        if not value:
            raise ValueError("API key cannot be empty")
        self.initialize(encrypted_credentials_exist=False)
        assert self._fernet is not None
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """JSON 암호문을 요청 snapshot에만 존재하는 credential 값으로 복원한다."""
        self.initialize(encrypted_credentials_exist=True)
        assert self._fernet is not None
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise LanguageModelCredentialError("Cannot decrypt LLM endpoint credential") from exc

    def _signature(self) -> tuple[int, int, int] | None:
        """key 파일의 교체·변경·유실을 감지할 안정적인 signature를 반환한다."""
        try:
            key_stat = self.key_file.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LanguageModelMasterKeyError("Cannot inspect LLM credential master key") from exc
        return (key_stat.st_ino, key_stat.st_size, key_stat.st_mtime_ns)

    def _create_key(self) -> None:
        """완성된 0600 key만 원자적으로 공개해 프로세스 간 경쟁을 안전하게 처리한다."""
        try:
            self.key_file.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.key_file.name}.",
                suffix=".tmp",
                dir=self.key_file.parent,
            )
        except OSError as exc:
            raise LanguageModelMasterKeyError("Cannot create LLM credential master key") from exc
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as key_stream:
                key_stream.write(Fernet.generate_key() + b"\n")
                key_stream.flush()
                os.fsync(key_stream.fileno())
            try:
                os.link(temporary_path, self.key_file)
            except FileExistsError:
                return
            directory_fd = os.open(self.key_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise LanguageModelMasterKeyError("Cannot create LLM credential master key") from exc
        finally:
            temporary_path.unlink(missing_ok=True)
