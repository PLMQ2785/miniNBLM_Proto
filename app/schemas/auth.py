import uuid

from pydantic import BaseModel, Field, field_validator

from app.password_policy import MIN_SECURE_PASSWORD_LENGTH


class LoginCredentials(BaseModel):
    """로그인 API가 받는 사용자명과 비밀번호 경계다."""
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """로그인 조회 전에 사용자명을 저장 형식으로 정규화한다."""
        return value.strip().casefold()


class RegistrationCredentials(LoginCredentials):
    """회원가입 API가 받는 강화된 자격 증명 경계다."""
    password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)


class PasswordChangeRequest(BaseModel):
    """비밀번호 변경 API의 현재·신규 비밀번호 경계다."""
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)



class AdminPasswordResetRequest(BaseModel):
    """관리자 비밀번호 초기화 API가 받는 입력 경계다."""
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    temporary_password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """관리자 조회 전에 사용자명을 저장 형식으로 정규화한다."""
        return value.strip().casefold()


class AccountDeleteRequest(BaseModel):
    """계정 삭제 API가 받는 본인 확인 입력 경계다."""
    current_password: str = Field(min_length=1, max_length=128)
    username_confirmation: str = Field(min_length=3, max_length=32)


class UserResponse(BaseModel):
    """인증 API가 외부에 노출하는 사용자 정보 경계다."""
    user_id: uuid.UUID
    username: str
    role: str
    must_change_password: bool


class AuthResponse(BaseModel):
    """로그인·가입 API가 반환하는 인증 응답 경계다."""
    user: UserResponse
