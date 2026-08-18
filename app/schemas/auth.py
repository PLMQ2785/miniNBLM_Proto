import uuid

from pydantic import BaseModel, Field, field_validator

from app.password_policy import MIN_SECURE_PASSWORD_LENGTH


class LoginCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class RegistrationCredentials(LoginCredentials):
    password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)



class AdminPasswordResetRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    temporary_password: str = Field(min_length=MIN_SECURE_PASSWORD_LENGTH, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class AccountDeleteRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    username_confirmation: str = Field(min_length=3, max_length=32)


class UserResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str
    must_change_password: bool


class AuthResponse(BaseModel):
    user: UserResponse
