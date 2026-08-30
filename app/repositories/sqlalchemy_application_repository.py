"""SQLAlchemy loan repository for later cutover; not used by active routes."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.loan_application import LoanApplication


class SqlAlchemyApplicationRepository:
    def __init__(self, database_session: Session):
        self._database_session = database_session

    def list_all(self) -> list[LoanApplication]:
        return list(self._database_session.scalars(select(LoanApplication).order_by(LoanApplication.id)))

    def get_by_application_id(self, application_id: str) -> LoanApplication | None:
        statement = select(LoanApplication).where(LoanApplication.application_id == application_id)
        return self._database_session.scalar(statement)

    def add(self, values: Mapping[str, object]) -> LoanApplication:
        application = LoanApplication(**dict(values))
        self._database_session.add(application)
        self._database_session.commit()
        self._database_session.refresh(application)
        return application