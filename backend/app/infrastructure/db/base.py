from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import LargeBinary, MetaData
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return a timezone-naive UTC value for MySQL DATETIME(6)."""
    return datetime.now(UTC).replace(tzinfo=None)


class UUIDBinary(TypeDecorator[UUID]):
    """Store UUIDs like UUID_TO_BIN(value, 1) and return UUID objects."""

    impl = LargeBinary(16)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.BINARY(16))
        return dialect.type_descriptor(LargeBinary(16))

    @staticmethod
    def _swap_time_parts(value: UUID) -> bytes:
        hexadecimal = value.hex
        swapped = hexadecimal[12:16] + hexadecimal[8:12] + hexadecimal[0:8] + hexadecimal[16:]
        return bytes.fromhex(swapped)

    @staticmethod
    def _restore_time_parts(value: bytes) -> UUID:
        hexadecimal = value.hex()
        restored = hexadecimal[8:16] + hexadecimal[4:8] + hexadecimal[0:4] + hexadecimal[16:]
        return UUID(hex=restored)

    def process_bind_param(self, value: UUID | str | None, dialect: Dialect) -> bytes | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, UUID):
            value = UUID(str(value))
        return self._swap_time_parts(value)

    def process_result_value(
        self, value: bytes | bytearray | memoryview | UUID | None, dialect: Dialect
    ) -> UUID | None:
        del dialect
        if value is None or isinstance(value, UUID):
            return value
        return self._restore_time_parts(bytes(value))


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
