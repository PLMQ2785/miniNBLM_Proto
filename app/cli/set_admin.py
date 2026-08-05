import argparse

from app.database import SessionLocal
from app.repositories import user_repository


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant or revoke the miniNBLM administrator role")
    parser.add_argument("username", help="Existing username")
    parser.add_argument("--revoke", action="store_true", help="Change the account back to the user role")
    args = parser.parse_args()

    username = args.username.strip().casefold()
    db = SessionLocal()
    try:
        user = user_repository.get_user_by_username(db, username)
        if user is None:
            raise SystemExit(f"User not found: {username}")
        role = "user" if args.revoke else "admin"
        user_repository.set_user_role(db, user, role)
        user_repository.set_password_change_required(db, user, not args.revoke)
        db.commit()
        print(f"{username}: role={role}, must_change_password={not args.revoke}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
