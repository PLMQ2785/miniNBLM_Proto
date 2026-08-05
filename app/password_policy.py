MIN_SECURE_PASSWORD_LENGTH = 12

COMMON_WEAK_PASSWORDS = frozenset({
    "admin",
    "adminadmin",
    "admin123",
    "admin1234",
    "changeme",
    "password",
    "password123",
    "password1234",
})


class PasswordPolicyError(ValueError):
    pass


def validate_secure_password(password: str, username: str | None = None) -> None:
    if len(password) < MIN_SECURE_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_SECURE_PASSWORD_LENGTH} characters long"
        )

    normalized = password.casefold()
    if normalized in COMMON_WEAK_PASSWORDS:
        raise PasswordPolicyError("Password is too common")
    if username and username.casefold() in normalized:
        raise PasswordPolicyError("Password must not contain the username")

    character_classes = sum((
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() for character in password),
    ))
    if character_classes < 3:
        raise PasswordPolicyError(
            "Password must use at least three of lowercase, uppercase, numbers, and symbols"
        )
