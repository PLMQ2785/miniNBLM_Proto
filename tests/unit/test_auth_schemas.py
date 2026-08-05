import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginCredentials, PasswordChangeRequest, RegistrationCredentials


def test_login_accepts_bootstrap_admin_password() -> None:
    credentials = LoginCredentials(username="ADMIN", password="admin")

    assert credentials.username == "admin"
    assert credentials.password == "admin"


def test_registration_requires_eight_character_password() -> None:
    with pytest.raises(ValidationError):
        RegistrationCredentials(username="student", password="short")


def test_password_change_requires_twelve_character_password() -> None:
    with pytest.raises(ValidationError):
        PasswordChangeRequest(current_password="old-password", new_password="TooShort1!")


@pytest.mark.parametrize("username", ["ab", "space user", "한글사용자"])
def test_invalid_usernames_are_rejected(username: str) -> None:
    with pytest.raises(ValidationError):
        LoginCredentials(username=username, password="password")
