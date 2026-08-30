"""Future SQL loan application model; existing loan storage remains JSON-backed."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    application_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    dob: Mapped[str | None] = mapped_column(String(10))
    age: Mapped[int | None] = mapped_column(Integer)
    mobile: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    pan_ciphertext: Mapped[str | None] = mapped_column(Text)
    pan_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    aadhaar_ciphertext: Mapped[str | None] = mapped_column(Text)
    aadhaar_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    employment_type: Mapped[str | None] = mapped_column(String(50))
    monthly_income: Mapped[float | None] = mapped_column(Numeric(14, 2))
    requested_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    tenure_months: Mapped[int | None] = mapped_column(Integer)
    loan_purpose: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    pin_code: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    emi: Mapped[float | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())