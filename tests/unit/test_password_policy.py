import pytest

from app.config import Settings
from app.password_policy import PasswordPolicyError, validate_secure_password


def test_secure_password_is_accepted() -> None:
    validate_secure_password("Nursing!Secure2026", "admin")


@pytest.mark.parametrize(
    ("password", "username"),
    [
        ("admin", "admin"),
        ("lowercaseonly", "admin"),
        ("Admin!Workspace2026", "admin"),
    ],
)
def test_insecure_password_is_rejected(password: str, username: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_secure_password(password, username)


def test_bootstrap_admin_can_be_disabled() -> None:
    configured = Settings(
        _env_file=None,
        bootstrap_admin_username=None,
        bootstrap_admin_password=None,
    )

    assert configured.bootstrap_admin_username is None
    assert configured.bootstrap_admin_password is None


def test_bootstrap_admin_requires_both_values() -> None:
    with pytest.raises(ValueError, match="must be set together"):
        Settings(
            _env_file=None,
            bootstrap_admin_username="admin",
            bootstrap_admin_password=None,
        )


def test_bootstrap_admin_rejects_weak_password() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        Settings(
            _env_file=None,
            bootstrap_admin_username="admin",
            bootstrap_admin_password="admin",
        )


def test_bootstrap_admin_username_is_normalized() -> None:
    configured = Settings(
        _env_file=None,
        bootstrap_admin_username="Initial.Admin",
        bootstrap_admin_password="Secure!Bootstrap2026",
    )

    assert configured.bootstrap_admin_username == "initial.admin"
