import fcntl
import hashlib
import json
import logging
import os
import stat
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.config import LLMConfigurationFile, LLMEndpoint
from app.services.language_model_credential_service import (
    LanguageModelCredentialCipher,
    LanguageModelCredentialError,
    LanguageModelMasterKeyError,
)


logger = logging.getLogger(__name__)


class LanguageModelConfigurationError(Exception):
    """endpoint JSON 또는 credential 참조가 유효하지 않음을 나타낸다."""


class LanguageModelConfigurationConflictError(Exception):
    """관리자가 읽은 뒤 endpoint JSON이 다른 작업으로 변경됐음을 나타낸다."""


@dataclass(frozen=True)
class LanguageModelSnapshot:
    """한 요청에서 공유할 검증된 endpoint 설정과 원본 revision이다."""

    revision: str
    configuration: LLMConfigurationFile
    endpoints: tuple[LLMEndpoint, ...]

    @property
    def default_endpoint(self) -> LLMEndpoint:
        """검증된 기본 endpoint snapshot을 반환한다."""
        return self.get_endpoint(self.configuration.default_endpoint)

    @property
    def enabled_endpoints(self) -> tuple[LLMEndpoint, ...]:
        """사용자가 선택할 수 있는 활성 endpoint만 반환한다."""
        return tuple(endpoint for endpoint in self.endpoints if endpoint.enabled)

    def get_endpoint(self, key: str, *, enabled_only: bool = False) -> LLMEndpoint:
        """지정 key의 endpoint를 조회하고 선택 경계에서는 비활성을 제외한다."""
        for endpoint in self.endpoints:
            if endpoint.key == key and (endpoint.enabled or not enabled_only):
                return endpoint
        raise KeyError(key)


class LanguageModelRegistry:
    """JSON을 유일한 원본으로 읽고 검증된 snapshot을 원자적으로 교체한다."""

    def __init__(
        self,
        endpoint_file: Path,
        master_key_file: Path,
        *,
        vision_caption_mode: str = "disabled",
    ) -> None:
        self.endpoint_file = endpoint_file.expanduser()
        self.master_key_file = master_key_file.expanduser()
        self.credential_cipher = LanguageModelCredentialCipher(self.master_key_file)
        self.vision_caption_mode = vision_caption_mode
        self.lock_file = self.endpoint_file.with_name(f".{self.endpoint_file.name}.lock")
        self._mutex = threading.RLock()
        self._snapshot: LanguageModelSnapshot | None = None
        self._observed_signature: tuple[object, ...] | None = None
        self._reload_error: str | None = None

    @property
    def reload_error(self) -> str | None:
        """최근 외부 파일 변경을 적용하지 못한 안전한 오류를 반환한다."""
        return self._reload_error

    def encrypt_api_key(self, api_key: str) -> str:
        """관리자가 입력한 API key를 현재 registry master key로 암호화한다."""
        return self.credential_cipher.encrypt(api_key)

    def initialize(self) -> LanguageModelSnapshot:
        """API 요청을 받기 전에 현재 JSON과 credential을 필수 검증한다."""
        with self._mutex:
            snapshot = self._read_snapshot()
            self._publish_snapshot(snapshot)
            return snapshot

    def snapshot(self) -> LanguageModelSnapshot:
        """파일 변경 시 lazy reload하고 실패하면 마지막 정상 snapshot을 유지한다."""
        with self._mutex:
            if self._snapshot is None:
                return self.initialize()
            signature = self._source_signature()
            if signature == self._observed_signature:
                return self._snapshot
            try:
                snapshot = self._read_snapshot()
            except LanguageModelConfigurationError as exc:
                self._observed_signature = signature
                self._reload_error = str(exc)
                logger.exception("Language model endpoint reload failed; keeping previous snapshot")
                return self._snapshot
            self._publish_snapshot(snapshot)
            logger.info("Language model endpoints reloaded: revision=%s", snapshot.revision)
            return snapshot

    def replace(
        self,
        configuration: LLMConfigurationFile,
        *,
        expected_revision: str,
        validate: Callable[[LanguageModelSnapshot], None] | None = None,
    ) -> LanguageModelSnapshot:
        """최신 revision을 확인하고 검증된 JSON을 같은 디렉터리에서 원자 교체한다."""
        self.endpoint_file.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with os.fdopen(lock_fd, "r+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                with self._mutex:
                    _, current_revision = self._read_configuration()
                    if current_revision != expected_revision:
                        raise LanguageModelConfigurationConflictError(
                            "Language model endpoint configuration changed; reload and retry"
                        )
                    serialized = self._serialize(configuration)
                    candidate = self._build_snapshot(configuration, serialized)
                    if validate is not None:
                        validate(candidate)
                    self._atomic_write(serialized)
                    self._publish_snapshot(candidate)
                    logger.info(
                        "Language model endpoints published: revision=%s",
                        candidate.revision,
                    )
                    return candidate
        except OSError as exc:
            raise LanguageModelConfigurationError("Cannot lock or replace the endpoint JSON") from exc

    def _read_snapshot(self) -> LanguageModelSnapshot:
        """현재 파일 bytes를 설정과 호출 가능한 endpoint snapshot으로 변환한다."""
        configuration, revision = self._read_configuration()
        return self._resolve(configuration, revision)

    def _read_configuration(self) -> tuple[LLMConfigurationFile, str]:
        """JSON 원본을 엄격하게 파싱하고 bytes revision을 계산한다."""
        try:
            raw = self.endpoint_file.read_bytes()
            payload = json.loads(raw)
            configuration = LLMConfigurationFile.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise LanguageModelConfigurationError(
                f"Cannot load LLM endpoint configuration from {self.endpoint_file}"
            ) from exc
        return configuration, self._revision(raw)

    def _build_snapshot(
        self,
        configuration: LLMConfigurationFile,
        serialized: bytes,
    ) -> LanguageModelSnapshot:
        """저장 예정 bytes와 해석된 credential을 하나의 candidate로 묶는다."""
        return self._resolve(configuration, self._revision(serialized))

    def _resolve(
        self,
        configuration: LLMConfigurationFile,
        revision: str,
    ) -> LanguageModelSnapshot:
        """master key와 모든 JSON 암호문을 검증해 요청 snapshot을 만든다."""
        encrypted_credentials_exist = any(
            endpoint.authentication == "managed"
            for endpoint in configuration.endpoints
        )
        try:
            self.credential_cipher.initialize(
                encrypted_credentials_exist=encrypted_credentials_exist
            )
            endpoints = tuple(
                endpoint.resolve(
                    "EMPTY"
                    if endpoint.authentication == "none"
                    else self.credential_cipher.decrypt(endpoint.api_key_ciphertext or "")
                )
                for endpoint in configuration.endpoints
            )
        except (
            LanguageModelCredentialError,
            LanguageModelMasterKeyError,
            ValueError,
        ) as exc:
            raise LanguageModelConfigurationError(str(exc)) from exc
        snapshot = LanguageModelSnapshot(
            revision=revision,
            configuration=configuration,
            endpoints=endpoints,
        )
        if self.vision_caption_mode != "disabled" and not snapshot.default_endpoint.supports_vision:
            raise LanguageModelConfigurationError(
                "The default LLM endpoint must support vision when captioning is enabled"
            )
        return snapshot

    def _publish_snapshot(self, snapshot: LanguageModelSnapshot) -> None:
        """정상 snapshot과 해당 원본 signature를 한 임계구역에서 공개한다."""
        self._snapshot = snapshot
        self._observed_signature = self._source_signature()
        self._reload_error = None

    def _source_signature(self) -> tuple[object, ...]:
        """endpoint JSON과 master key의 교체·변경·유실을 감지한다."""
        return (
            self._file_signature(self.endpoint_file),
            self._file_signature(self.master_key_file),
        )

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int, int] | tuple[str]:
        """파일 교체와 내용 변경을 감지하며 누락도 안정적인 값으로 표현한다."""
        try:
            stat = path.stat()
        except OSError:
            return ("missing",)
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns)

    @staticmethod
    def _revision(raw: bytes) -> str:
        """관리자 동시 수정 충돌을 탐지할 원본 SHA-256 revision을 계산한다."""
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _serialize(configuration: LLMConfigurationFile) -> bytes:
        """관리자가 읽을 수 있는 안정적인 JSON bytes를 생성한다."""
        payload = configuration.model_dump(mode="json", exclude_none=True)
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def _atomic_write(self, serialized: bytes) -> None:
        """기존 소유권·권한을 보존하며 임시 파일을 fsync 후 원자 교체한다."""
        current_stat = self.endpoint_file.stat()
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.endpoint_file.name}.",
            suffix=".tmp",
            dir=self.endpoint_file.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(fd, stat.S_IMODE(current_stat.st_mode))
            try:
                os.fchown(fd, current_stat.st_uid, current_stat.st_gid)
            except PermissionError:
                pass
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.endpoint_file)
            directory_fd = os.open(self.endpoint_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary_path.unlink(missing_ok=True)
