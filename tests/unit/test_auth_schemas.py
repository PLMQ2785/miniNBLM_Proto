import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginCredentials, PasswordChangeRequest, RegistrationCredentials


def test_login_accepts_bootstrap_admin_password() -> None:
    """로그인은 초기 관리자용 짧은 비밀번호를 그대로 허용한다."""
    credentials = LoginCredentials(username="ADMIN", password="admin")

    assert credentials.username == "admin"
    assert credentials.password == "admin"


def test_registration_requires_eight_character_password() -> None:
    """회원 가입 비밀번호는 최소 여덟 글자여야 한다."""
    with pytest.raises(ValidationError):
        RegistrationCredentials(username="student", password="short")


def test_password_change_requires_eight_character_password() -> None:
    """새 비밀번호가 여덟 글자보다 짧으면 변경 요청을 거부한다."""
    with pytest.raises(ValidationError):
        PasswordChangeRequest(current_password="old-password", new_password="Ab1!xyz")


def test_password_change_accepts_eight_character_password() -> None:
    """여덟 글자인 새 비밀번호는 변경 요청에 사용할 수 있다."""
    credentials = PasswordChangeRequest(
        current_password="old-password",
        new_password="Safe!123",
    )

    assert credentials.new_password == "Safe!123"


@pytest.mark.parametrize("username", ["ab", "space user", "한글사용자"])
def test_invalid_usernames_are_rejected(username: str) -> None:
    """허용 형식을 벗어난 사용자 이름은 로그인 단계에서 거부한다."""
    with pytest.raises(ValidationError):
        LoginCredentials(username=username, password="password")
