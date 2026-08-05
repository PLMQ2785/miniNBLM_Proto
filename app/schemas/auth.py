import uuid

from pydantic import BaseModel, Field, field_validator


class LoginCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class RegistrationCredentials(LoginCredentials):
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str


class AuthResponse(BaseModel):
    user: UserResponse
