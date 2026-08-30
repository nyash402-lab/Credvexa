"""SQLAlchemy user repository for later cutover; not used by active routes."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class SqlAlchemyUserRepository:
    def __init__(self, database_session: Session):
        self._database_session = database_session

    def list_all(self) -> list[User]:
        return list(self._database_session.scalars(select(User).order_by(User.id)))

    def get_by_email_or_mobile(self, email_or_mobile: str) -> User | None:
        statement = select(User).where((User.email == email_or_mobile) | (User.mobile == email_or_mobile))
        return self._database_session.scalar(statement)

    def add(self, values: Mapping[str, object]) -> User:
        user = User(**dict(values))
        self._database_session.add(user)
        self._database_session.commit()
        self._database_session.refresh(user)
        return user