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
        db.commit()
        print(f"{username}: role={role}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
