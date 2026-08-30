"""Database models imported here for Alembic metadata discovery."""

from app.models.application_event import ApplicationEvent
from app.models.loan_application import LoanApplication
from app.models.otp_challenge import OTPChallenge
from app.models.user import User

__all__ = ["ApplicationEvent", "LoanApplication", "OTPChallenge", "User"]