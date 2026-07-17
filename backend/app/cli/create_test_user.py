"""Create an idempotent local-development user with a securely hashed password."""

import argparse
import asyncio
from dataclasses import dataclass
from getpass import getpass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.ids import uuid7
from app.core.security import PasswordService
from app.infrastructure.db.models.identity import Role, User, UserRole

ROLE_NAMES: Final[dict[str, str]] = {
    "USER": "普通用户",
    "PLATFORM_ADMIN": "平台管理员",
    "KB_ADMIN": "知识库管理员",
    "OPS_ADMIN": "运维管理员",
    "MODEL_ADMIN": "模型管理员",
    "MERCHANT_ADMIN": "商家管理员",
    "MERCHANT_OPERATOR": "商家运营人员",
}


@dataclass(frozen=True, slots=True)
class CreateUserResult:
    username: str
    role_code: str
    user_created: bool
    role_created: bool
    role_assigned: bool


def _normalized_username(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError("username must not be blank")
    if len(normalized) > 64:
        raise ValueError("username must contain at most 64 characters")
    return normalized


def _normalized_role(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in ROLE_NAMES:
        supported = ", ".join(ROLE_NAMES)
        raise ValueError(f"unsupported role {value!r}; choose one of: {supported}")
    return normalized


def _normalized_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if len(normalized) > 254 or "@" not in normalized:
        raise ValueError("email must be a valid address with at most 254 characters")
    return normalized


async def create_or_update_test_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str | None,
    email: str | None,
    role_code: str,
) -> CreateUserResult:
    normalized_username = _normalized_username(username)
    normalized_email = _normalized_email(email)
    normalized_role = _normalized_role(role_code)
    if not password:
        raise ValueError("password must not be blank")

    password_hash = PasswordService().hash(password)
    user = await session.scalar(
        select(User).where(User.normalized_username == normalized_username).with_for_update()
    )
    user_created = user is None
    if user is None:
        user = User(
            id=uuid7(),
            username=username.strip(),
            normalized_username=normalized_username,
            email=normalized_email,
            normalized_email=normalized_email,
            password_hash=password_hash,
            display_name=(display_name or username).strip(),
            status="ACTIVE",
        )
        session.add(user)
    else:
        user.username = username.strip()
        user.password_hash = password_hash
        user.display_name = (display_name or user.display_name or username).strip()
        user.email = normalized_email
        user.normalized_email = normalized_email
        user.status = "ACTIVE"
        user.login_failed_count = 0
        user.locked_until = None
        user.deleted_at = None

    role = await session.scalar(select(Role).where(Role.code == normalized_role).with_for_update())
    role_created = role is None
    if role is None:
        role = Role(
            id=uuid7(),
            code=normalized_role,
            name=ROLE_NAMES[normalized_role],
            is_system=True,
            status="ACTIVE",
        )
        session.add(role)
    else:
        role.status = "ACTIVE"

    assignment = await session.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    )
    role_assigned = assignment is None
    if assignment is None:
        session.add(UserRole(user_id=user.id, role_id=role.id))

    return CreateUserResult(
        username=user.username,
        role_code=role.code,
        user_created=user_created,
        role_created=role_created,
        role_assigned=role_assigned,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or update a test account in the local development database."
    )
    parser.add_argument("--username", required=True, help="Login username")
    parser.add_argument("--display-name", help="Display name; defaults to the username")
    parser.add_argument("--email", help="Optional email address")
    parser.add_argument(
        "--role",
        default="USER",
        choices=tuple(ROLE_NAMES),
        help="Frontend role to assign (default: USER)",
    )
    return parser


async def _run(args: argparse.Namespace, password: str) -> CreateUserResult:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with AsyncSession(engine) as session, session.begin():
            return await create_or_update_test_user(
                session,
                username=args.username,
                password=password,
                display_name=args.display_name,
                email=args.email,
                role_code=args.role,
            )
    finally:
        await engine.dispose()


def main() -> None:
    args = _parser().parse_args()
    password = getpass("Test account password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match; no database changes were made.")
    try:
        result = asyncio.run(_run(args, password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    action = "created" if result.user_created else "updated"
    role_action = "assigned" if result.role_assigned else "already assigned"
    print(f"Test account {result.username!r} {action}; role {result.role_code!r} {role_action}.")


if __name__ == "__main__":
    main()
