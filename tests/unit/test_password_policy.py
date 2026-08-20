import pytest

from app.config import Settings
from app.password_policy import PasswordPolicyError, validate_secure_password


def test_secure_password_is_accepted() -> None:
    """복잡도 기준을 만족하는 비밀번호는 오류 없이 통과한다."""
    validate_secure_password("Safe!123", "admin")


@pytest.mark.parametrize(
    ("password", "username"),
    [
        ("admin", "admin"),
        ("lowercaseonly", "admin"),
        ("Admin!Workspace2026", "admin"),
    ],
)
def test_insecure_password_is_rejected(password: str, username: str) -> None:
    """취약하거나 사용자 정보와 연관된 비밀번호는 거부한다."""
    with pytest.raises(PasswordPolicyError):
        validate_secure_password(password, username)


def test_bootstrap_admin_can_be_disabled() -> None:
    """초기 관리자 자격 증명은 두 값 모두 비워 비활성화할 수 있다."""
    configured = Settings(
        _env_file=None,
        bootstrap_admin_username=None,
        bootstrap_admin_password=None,
    )

    assert configured.bootstrap_admin_username is None
    assert configured.bootstrap_admin_password is None


def test_bootstrap_admin_requires_both_values() -> None:
    """초기 관리자 이름과 비밀번호는 함께 설정해야 한다."""
    with pytest.raises(ValueError, match="must be set together"):
        Settings(
            _env_file=None,
            bootstrap_admin_username="admin",
            bootstrap_admin_password=None,
        )


def test_bootstrap_admin_rejects_short_password() -> None:
    """초기 관리자 비밀번호에도 최소 길이 기준을 적용한다."""
    with pytest.raises(ValueError, match="at least 8"):
        Settings(
            _env_file=None,
            bootstrap_admin_username="admin",
            bootstrap_admin_password="Ab1!xyz",
        )


def test_bootstrap_admin_username_is_normalized() -> None:
    """초기 관리자 사용자 이름은 비교 가능한 소문자로 정규화한다."""
    configured = Settings(
        _env_file=None,
        bootstrap_admin_username="Initial.Admin",
        bootstrap_admin_password="Secure!Bootstrap2026",
    )

    assert configured.bootstrap_admin_username == "initial.admin"
