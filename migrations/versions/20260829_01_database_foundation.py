"""Create database foundation tables.

Revision ID: 20260829_01
Revises:
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legacy_user_id", sa.String(length=32), unique=True),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), unique=True),
        sa.Column("mobile", sa.String(length=20), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_legacy_user_id", "users", ["legacy_user_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_mobile", "users", ["mobile"], unique=True)

    op.create_table(
        "loan_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("application_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("dob", sa.String(length=10)), sa.Column("age", sa.Integer()),
        sa.Column("mobile", sa.String(length=20), nullable=False), sa.Column("email", sa.String(length=255)),
        sa.Column("pan_ciphertext", sa.Text()), sa.Column("pan_digest", sa.String(length=64)),
        sa.Column("aadhaar_ciphertext", sa.Text()), sa.Column("aadhaar_digest", sa.String(length=64)),
        sa.Column("employment_type", sa.String(length=50)), sa.Column("monthly_income", sa.Numeric(14, 2)),
        sa.Column("requested_amount", sa.Numeric(14, 2)), sa.Column("tenure_months", sa.Integer()),
        sa.Column("loan_purpose", sa.String(length=200)), sa.Column("city", sa.String(length=100)),
        sa.Column("state", sa.String(length=100)), sa.Column("pin_code", sa.String(length=12)),
        sa.Column("status", sa.String(length=50), nullable=False), sa.Column("emi", sa.Numeric(14, 2)),
        sa.Column("note", sa.Text()), sa.Column("rejection_reason", sa.Text()), sa.Column("rejected_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_loan_applications_user_id", "loan_applications", ["user_id"])
    op.create_index("ix_loan_applications_application_id", "loan_applications", ["application_id"], unique=True)
    op.create_index("ix_loan_applications_mobile", "loan_applications", ["mobile"])
    op.create_index("ix_loan_applications_status", "loan_applications", ["status"])
    op.create_index("ix_loan_applications_pan_digest", "loan_applications", ["pan_digest"])
    op.create_index("ix_loan_applications_aadhaar_digest", "loan_applications", ["aadhaar_digest"])

    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("mobile", sa.String(length=20), nullable=False), sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("otp_digest", sa.String(length=255)), sa.Column("provider_reference", sa.String(length=128)),
        sa.Column("status", sa.String(length=30), nullable=False), sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("sent_at", sa.DateTime()),
        sa.Column("verified_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_otp_challenges_user_id", "otp_challenges", ["user_id"])
    op.create_index("ix_otp_challenges_mobile", "otp_challenges", ["mobile"])
    op.create_index("ix_otp_challenges_provider_reference", "otp_challenges", ["provider_reference"])
    op.create_index("ix_otp_challenges_expires_at", "otp_challenges", ["expires_at"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("loan_applications.id"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(length=100), nullable=False), sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=64)), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])
    op.create_index("ix_application_events_actor_user_id", "application_events", ["actor_user_id"])
    op.create_index("ix_application_events_request_id", "application_events", ["request_id"])


def downgrade() -> None:
    op.drop_table("application_events")
    op.drop_table("otp_challenges")
    op.drop_table("loan_applications")
    op.drop_table("users")