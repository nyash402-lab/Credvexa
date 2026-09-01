from __future__ import annotations

import json
import math
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

from app.config import get_settings
from app.database import init_database
from app.services.candidate_service import get_saved_approved_amount, save_approved_amount


APP_NAME = "Credvexa"
FIXED_INTEREST_RATE = 11.5
DATA_FILE = Path(__file__).with_name("credvexa_data.json")

settings = get_settings()
app = Flask(__name__)
app.config["SECRET_KEY"] = settings.secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure
init_database(app)


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_applications():
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_applications(applications):
    with DATA_FILE.open("w", encoding="utf-8") as file:
        json.dump(applications, file, indent=2)


def validate_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"[6-9]\d{9}", str(value).strip()))


def validate_email(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", str(value).strip()))


def validate_pan(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", str(value).strip().upper()))


def calculate_emi(principal: float, rate: float, months: int) -> float:
    principal = float(principal or 0)
    months = int(months or 0)
    if principal <= 0 or months <= 0:
        return 0.0
    monthly_rate = (float(rate) / 100) / 12
    if monthly_rate == 0:
        return principal / months
    return principal * monthly_rate * ((1 + monthly_rate) ** months) / (((1 + monthly_rate) ** months) - 1)


def generate_application_id():
    stamp = datetime.now().strftime("%d%m%y")
    suffix = random.randint(1000, 9999)
    return f"CRX{stamp}{suffix}"


def get_all_applications():
    return load_applications()


def find_application(application_id: str = None, mobile: str = None):
    for item in load_applications():
        if application_id and item.get("application_id") == application_id:
            return item
        if mobile and str(item.get("mobile", "")).strip() == str(mobile).strip():
            return item
    return None


def create_application(payload):
    required = [
        "full_name",
        "mobile",
        "email",
        "pan",
        "monthly_income",
        "requested_amount",
        "tenure_months",
        "loan_purpose",
        "city",
        "state",
        "pin_code",
    ]
    for field_name in required:
        if field_name not in payload or str(payload.get(field_name, "")).strip() in ("", "None"):
            raise ValueError(f"Missing required field: {field_name}")

    if not validate_mobile(payload["mobile"]):
        raise ValueError("Please enter a valid 10-digit Indian mobile number.")
    if not validate_email(payload["email"]):
        raise ValueError("Please enter a valid email address.")
    if not validate_pan(payload["pan"]):
        raise ValueError("Please enter a valid PAN format, e.g. ABCDE1234F.")

    monthly_income = float(payload["monthly_income"])
    requested_amount = float(payload["requested_amount"])
    tenure_months = int(payload["tenure_months"])
    if monthly_income <= 0 or requested_amount <= 0 or tenure_months <= 0:
        raise ValueError("Income, amount, and tenure must all be greater than zero.")

    date_of_birth = str(payload.get("dob", "")).strip()
    age = int(payload.get("age") or calculate_age(date_of_birth) or 25)
    aadhaar = str(payload.get("aadhaar", "")).strip()
    if not validate_aadhaar(aadhaar):
        raise ValueError("Please enter a valid 12-digit Aadhaar number for demo testing.")

    application = {
        "application_id": generate_application_id(),
        "full_name": str(payload["full_name"]).strip(),
        "dob": date_of_birth,
        "age": age,
        "mobile": str(payload["mobile"]).strip(),
        "email": str(payload["email"]).strip(),
        "pan": str(payload["pan"]).strip().upper(),
        "aadhaar": aadhaar,
        "employment_type": str(payload.get("employment_type", "Salaried")).strip() or "Salaried",
        "monthly_income": monthly_income,
        "requested_amount": requested_amount,
        "tenure_months": tenure_months,
        "loan_purpose": str(payload["loan_purpose"]).strip(),
        "city": str(payload["city"]).strip(),
        "state": str(payload["state"]).strip(),
        "pin_code": str(payload["pin_code"]).strip(),
        "status": "UNDER_REVIEW",
        "emi": round(calculate_emi(requested_amount, FIXED_INTEREST_RATE, tenure_months), 2),
        "note": "Application submitted. Final approval depends on verification, documentation and underwriting review.",
        "created_at": now_stamp(),
        "updated_at": now_stamp(),
    }

    records = load_applications()
    records.append(application)
    save_applications(records)
    return application


def update_application_status(application_id: str, new_status: str, note: str = ""):
    records = load_applications()
    for record in records:
        if record.get("application_id") == application_id:
            normalized_status = str(new_status).strip().upper()
            record["status"] = normalized_status

            if normalized_status == "REJECTED":
                if not note:
                    note = generate_rejection_reason()
                record["rejection_reason"] = note
                record["rejected_at"] = now_stamp()
            else:
                record.pop("rejection_reason", None)
                record.pop("rejected_at", None)

            if note:
                record["note"] = note
            record["updated_at"] = now_stamp()
            save_applications(records)
            return record
    raise ValueError("Application not found.")


USERS_FILE = Path(__file__).with_name("credvexa_users.json")

load_dotenv(Path(__file__).with_name(".env"))

MSG91_AUTH_TOKEN = str(os.getenv("MSG91_AUTH_TOKEN", "")).strip()
MSG91_OTP_WIDGET_ID = str(os.getenv("MSG91_OTP_WIDGET_ID", "")).strip()
MSG91_OTP_WIDGET_TOKEN_AUTH = str(os.getenv("MSG91_OTP_WIDGET_TOKEN_AUTH", "")).strip()
MSG91_OTP_WIDGET_VERIFY_URL = str(os.getenv("MSG91_OTP_WIDGET_VERIFY_URL", "https://control.msg91.com/api/v5/widget/verifyAccessToken")).strip()


def normalize_msg91_mobile(mobile: str) -> str:
    digits = str(mobile or "").strip().replace("+", "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("91") and len(digits) == 12:
        return digits
    if len(digits) == 10:
      return f"91{digits}"
    return digits


def verify_msg91_widget_access_token(access_token: str):
    if not MSG91_AUTH_TOKEN:
        raise RuntimeError("MSG91 authentication is not configured.")
    if not access_token:
        raise ValueError("Missing OTP verification token.")

    try:
        response = requests.post(
            MSG91_OTP_WIDGET_VERIFY_URL,
          json={"authkey": MSG91_AUTH_TOKEN, "access-token": access_token},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError("MSG91 token verification is unavailable.") from exc

    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}

    status_value = str(data.get("type") or data.get("status") or "").lower()
    if response.status_code >= 400 or status_value in {"error", "failed", "invalid", "expired"}:
        raise ValueError("Invalid OTP verification token.")
    return data


def load_users():
    if not USERS_FILE.exists():
        return []
    try:
        with USERS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_users(users):
    with USERS_FILE.open("w", encoding="utf-8") as file:
        json.dump(users, file, indent=2)


def validate_aadhaar(value: str) -> bool:
    return bool(re.fullmatch(r"\d{12}", str(value).strip()))


def calculate_age(date_of_birth: str):
    if not date_of_birth:
        return 0
    try:
        dob = datetime.strptime(str(date_of_birth), "%Y-%m-%d")
        today = datetime.now()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return max(age, 18)
    except Exception:
        return 0


def generate_age_based_offer(age: int):
    age = int(age or 25)
    if age <= 21:
        choices = [30000, 32000, 35000, 40000]
    elif age <= 25:
        choices = [50000, 67000, 80000]
    elif age <= 30:
        choices = [70000, 85000, 100000]
    else:
        choices = [100000, 150000, 200000]
    return random.choice(choices)


def create_user_account(payload):
    required = ["full_name", "email", "mobile", "password"]
    for field_name in required:
        if field_name not in payload or str(payload.get(field_name, "")).strip() in ("", "None"):
            raise ValueError(f"Missing required field: {field_name}")

    email = str(payload["email"]).strip().lower()
    mobile = str(payload["mobile"]).strip()
    password = str(payload["password"]).strip()
    if not validate_email(email):
        raise ValueError("Please enter a valid email address.")
    if not validate_mobile(mobile):
        raise ValueError("Please enter a valid 10-digit mobile number.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    users = load_users()
    if any(str(item.get("email", "")).strip().lower() == email or str(item.get("mobile", "")).strip() == mobile for item in users):
        raise ValueError("An account with this email or mobile number already exists.")

    user = {
        "id": f"USR{random.randint(1000, 9999)}",
        "full_name": str(payload["full_name"]).strip(),
        "email": email,
        "mobile": mobile,
        "password": password,
        "created_at": now_stamp(),
    }
    users.append(user)
    save_users(users)
    return user


def authenticate_user(email_or_mobile: str, password: str):
    users = load_users()
    for user in users:
        if str(user.get("email", "")).strip().lower() == str(email_or_mobile).strip().lower():
            if str(user.get("password", "")) == str(password):
                return user
        if str(user.get("mobile", "")).strip() == str(email_or_mobile).strip():
            if str(user.get("password", "")) == str(password):
                return user
    return None


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CREDVEXA | Personal Loans</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #FFFFFF;
        --surface: #F6F9FD;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --error: #D92D20;
        --warning: #D97706;
        --shadow-soft: 0 12px 32px rgba(11, 61, 145, 0.08);
        --shadow-medium: 0 22px 54px rgba(11, 61, 145, 0.10);
      }
      * { box-sizing: border-box; }
      html { scroll-behavior: smooth; }
      body {
        margin: 0;
        font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
      }
      a { color: var(--secondary); text-decoration: none; transition: all 200ms ease; }
      a:hover { color: var(--primary); }
      img { max-width: 100%; display: block; }
      button, input, select, textarea { font: inherit; }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 40;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(228, 234, 242, 0.8);
      }
      .brand {
        display: inline-flex;
        align-items: center;
        gap: 0.7rem;
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        color: var(--primary);
        line-height: 1;
      }
      .header-actions {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
      }
      .header-actions a {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0.7rem 1rem;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: #fff;
        color: var(--text);
        font-weight: 700;
      }
      .header-actions .primary {
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        border-color: transparent;
      }
      .brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-size: 0.95rem;
        box-shadow: 0 8px 18px rgba(29, 95, 233, 0.25);
      }
      nav {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
      }
      nav a {
        color: var(--text);
        font-weight: 600;
        padding: 0.4rem 0.65rem;
        border-radius: 999px;
      }
      nav a:hover, nav a:focus-visible {
        background: var(--primary-soft);
        color: var(--primary);
      }
      main { background: var(--bg); }
      .hero {
        max-width: 1200px;
        margin: 0 auto;
        padding: 4rem 2rem 2rem;
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 2rem;
        align-items: center;
      }
      .eyebrow {
        letter-spacing: 0.12em;
        font-size: 0.72rem;
        color: var(--secondary);
        font-weight: 800;
        text-transform: uppercase;
      }
      .hero-copy h1 {
        font-size: clamp(2.5rem, 5vw, 4rem);
        line-height: 1.08;
        margin: 0.7rem 0 1rem;
      }
      .hero-highlight {
        color: var(--primary);
        font-size: clamp(1.25rem, 2vw, 1.9rem);
        font-weight: 700;
        margin: 0 0 1rem;
      }
      .hero-copy p {
        color: var(--muted);
        font-size: 1.05rem;
        max-width: 620px;
      }
      .trust-points {
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        margin-top: 1.2rem;
      }
      .trust-item {
        background: var(--primary-soft);
        border: 1px solid rgba(29, 95, 233, 0.08);
        color: var(--primary);
        border-radius: 999px;
        padding: 0.6rem 0.9rem;
        font-weight: 700;
        font-size: 0.9rem;
      }
      .cta-row {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
        margin-top: 1.5rem;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: none;
        border-radius: 12px;
        padding: 0.9rem 1.4rem;
        font-weight: 700;
        cursor: pointer;
        transition: transform 200ms ease, box-shadow 200ms ease;
      }
      .btn:hover { transform: translateY(-1px); }
      .btn.primary {
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        box-shadow: 0 16px 30px rgba(29, 95, 233, 0.2);
      }
      .btn.secondary {
        background: #fff;
        color: var(--primary);
        border: 1px solid var(--border);
      }
      .hero-card {
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 28px;
        box-shadow: var(--shadow-medium);
        padding: 1.5rem;
      }
      .phone-badge {
        display: inline-block;
        background: rgba(11, 92, 255, 0.08);
        color: var(--primary);
        border-radius: 999px;
        padding: 0.4rem 0.7rem;
        font-size: 0.76rem;
        font-weight: 700;
        margin-bottom: 0.8rem;
      }
      .hero-card h3 {
        margin: 0 0 1rem;
        font-size: 1.8rem;
      }
      .hero-card label {
        display: block;
        font-weight: 700;
        color: var(--text);
        margin-bottom: 0.5rem;
      }
      .hero-card input {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.9rem 1rem;
        font-size: 1rem;
        margin-top: 0.4rem;
      }
      .check-wrap {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        margin: 1rem 0;
        color: var(--muted);
        font-size: 0.88rem;
      }
      .check-wrap input { width: 1rem; height: 1rem; margin-top: 0.2rem; }
      .mini-meta {
        display: flex;
        justify-content: space-between;
        gap: 0.5rem;
        margin-top: 1rem;
        color: var(--muted);
        font-size: 0.8rem;
      }
      .disclaimer {
        margin-top: 1.1rem;
        color: var(--muted);
        font-size: 0.78rem;
      }
      .feature-band {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 2rem 2rem;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1.2rem;
      }
      .feature-card {
        background: linear-gradient(180deg, #ffffff 0%, #f5f9ff 100%);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 1.6rem;
        transition: transform 220ms ease, box-shadow 220ms ease;
      }
      .feature-card:hover {
        transform: translateY(-4px);
        box-shadow: var(--shadow-soft);
      }
      .feature-icon {
        width: 3rem;
        height: 3rem;
        display: grid;
        place-items: center;
        font-size: 1.6rem;
        background: var(--primary-soft);
        border-radius: 14px;
        margin-bottom: 1rem;
      }
      .feature-card h3 { margin: 0 0 0.5rem; }
      .feature-card p { margin: 0; color: var(--muted); }
      .showcase-section {
        background: linear-gradient(180deg, #f5f9ff 0%, #ffffff 100%);
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 2rem;
        align-items: center;
        max-width: 1200px;
        margin: 0 auto;
        padding: 4rem 2rem;
      }
      .showcase-copy h2, .section-heading h2 {
        font-size: clamp(2rem, 3vw, 3rem);
        color: var(--text);
        margin: 0.4rem 0 1.2rem;
      }
      .showcase-list {
        display: grid;
        gap: 1rem;
      }
      .showcase-item {
        display: flex;
        align-items: flex-start;
        gap: 1rem;
        padding: 1rem 1.1rem;
        background: #fff;
        border-radius: 18px;
        border: 1px solid var(--border);
      }
      .showcase-number {
        width: 2.5rem;
        height: 2.5rem;
        display: grid;
        place-items: center;
        border-radius: 12px;
        background: var(--primary-soft);
        color: var(--primary);
        font-weight: 800;
      }
      .showcase-item h4 { margin: 0; }
      .showcase-item p { margin: 0.3rem 0 0; color: var(--muted); }
      .phone-mockup {
        display: flex;
        justify-content: center;
        align-items: center;
      }
      .phone-screen {
        width: min(100%, 330px);
        background: linear-gradient(180deg, #102447 0%, #1b3d7a 100%);
        border-radius: 32px;
        padding: 1.2rem;
        box-shadow: 0 26px 55px rgba(12, 43, 94, 0.22);
      }
      .screen-top {
        display: flex;
        justify-content: space-between;
        color: #dfe9ff;
        font-weight: 600;
        font-size: 0.86rem;
      }
      .dot {
        width: 0.65rem;
        height: 0.65rem;
        border-radius: 50%;
        background: #7ee0a2;
      }
      .screen-box {
        background: rgba(255,255,255,0.12);
        border-radius: 16px;
        color: #fff;
        padding: 1rem;
        margin-top: 1rem;
      }
      .primary-box {
        font-size: 1.8rem;
        font-weight: 800;
      }
      .small-box {
        font-weight: 700;
      }
      .screen-chart {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.6rem;
        align-items: end;
        height: 90px;
        margin-top: 1.2rem;
      }
      .screen-chart span {
        display: block;
        background: linear-gradient(180deg, #8cc7ff 0%, #5ea5ff 100%);
        border-radius: 12px 12px 0 0;
      }
      .screen-chart span:nth-child(1) { height: 35%; }
      .screen-chart span:nth-child(2) { height: 50%; }
      .screen-chart span:nth-child(3) { height: 68%; }
      .screen-chart span:nth-child(4) { height: 88%; }
      .stats-section {
        max-width: 1200px;
        margin: 0 auto;
        padding: 4rem 2rem 2rem;
      }
      .section-heading { text-align: center; }
      .stats-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1.2rem;
        margin-top: 2rem;
      }
      .stat-card {
        background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 1.5rem;
        text-align: center;
      }
      .stat-number {
        font-size: clamp(1.9rem, 4vw, 2.8rem);
        font-weight: 800;
        color: var(--primary);
      }
      .stat-label {
        color: var(--muted);
        font-weight: 700;
      }
      .calculator-card {
        max-width: 1200px;
        margin: 2.5rem auto 0;
        padding: 2rem;
        background: linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%);
        border: 1px solid var(--border);
        border-radius: 28px;
        box-shadow: var(--shadow-soft);
      }
      .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        margin-bottom: 1.2rem;
      }
      .section-header h2 { margin: 0; }
      .section-header p { margin: 0; color: var(--muted); }
      .grid-2 {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1.2rem;
      }
      .grid-2 label {
        display: block;
        font-weight: 700;
        color: var(--text);
      }
      .grid-2 input, .grid-2 select {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.9rem 1rem;
        margin-top: 0.4rem;
      }
      .result-box {
        display: grid;
        gap: 0.8rem;
        background: var(--primary-soft);
        border: 1px solid rgba(29, 95, 233, 0.08);
        border-radius: 18px;
        padding: 1rem;
      }
      .result-item {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        font-weight: 700;
      }
      .reviews-section {
        max-width: 1200px;
        margin: 0 auto;
        padding: 4rem 2rem 2rem;
      }
      .reviews-slider {
        margin-top: 2rem;
      }
      .review-track {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1.2rem;
      }
      .review-card {
        background: linear-gradient(180deg, #fff 0%, #f7faff 100%);
        border: 1px solid var(--border);
        border-radius: 22px;
        padding: 1.4rem;
      }
      .review-top {
        display: flex;
        align-items: center;
        gap: 0.8rem;
        margin-bottom: 1rem;
      }
      .avatar {
        width: 2.8rem;
        height: 2.8rem;
        border-radius: 50%;
        display: grid;
        place-items: center;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-weight: 700;
      }
      .avatar.alt { background: linear-gradient(135deg, #1b4d9c, #6ea9ff); }
      .stars { color: #f5b301; letter-spacing: 0.1em; margin-bottom: 0.8rem; }
      .review-card p { margin: 0; color: var(--muted); }
      .site-footer {
        background: linear-gradient(180deg, #0b1d3d 0%, #0c2348 100%);
        color: #edf5ff;
        margin-top: 4rem;
        border-top: 1px solid rgba(121, 158, 255, 0.24);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 -18px 34px rgba(7, 20, 40, 0.42);
      }
      .site-footer-inner {
        position: relative;
        max-width: 1200px;
        margin: 0 auto;
        padding: 3rem 2rem 1.5rem;
        display: grid;
        grid-template-columns: 1.6fr 1fr 1fr 1.2fr;
        gap: 2rem;
      }
      .site-footer-inner::before {
        content: "";
        position: absolute;
        left: 2rem;
        right: 2rem;
        top: 0;
        height: 1px;
        background: linear-gradient(90deg, rgba(138, 163, 255, 0), rgba(138, 163, 255, 0.9), rgba(138, 163, 255, 0));
        box-shadow: 0 0 18px rgba(138, 163, 255, 0.42);
      }
      .site-footer .brand {
        color: #fff;
        font-size: 1.35rem;
      }
      .site-footer .brand-mark {
        background: linear-gradient(135deg, #4e85ff, #1d5fe9);
        color: #ffffff;
        box-shadow: 0 0 18px rgba(64, 112, 255, 0.34);
        border: 1px solid rgba(155, 184, 255, 0.7);
      }
      .brand-block {
        position: relative;
      }
      .brand-block::before {
        content: "";
        display: block;
        width: 84px;
        height: 2px;
        margin-bottom: 1rem;
        border-radius: 999px;
        background: linear-gradient(90deg, #9bb5ff, rgba(155, 181, 255, 0));
        box-shadow: 0 0 16px rgba(155, 181, 255, 0.4);
      }
      .brand-block p {
        margin: 1rem 0 1.2rem;
        color: rgba(235, 243, 255, 0.72);
        line-height: 1.7;
        max-width: 32ch;
      }
      .footer-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
      }
      .footer-badges span {
        display: inline-flex;
        align-items: center;
        padding: 0.4rem 0.7rem;
        border-radius: 999px;
        background: rgba(145, 170, 255, 0.08);
        border: 1px solid rgba(145, 170, 255, 0.22);
        color: #dfe9ff;
        font-size: 0.69rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
      }
      .footer-section h4 {
        margin: 0 0 0.9rem;
        font-size: 0.78rem;
        color: #dfe9ff;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .footer-links {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 0.7rem;
      }
      .footer-links a {
        color: rgba(235, 243, 255, 0.72);
        text-decoration: none;
        transition: color 200ms ease, padding-left 200ms ease;
      }
      .footer-links a:hover {
        color: #ffffff;
        padding-left: 0.25rem;
      }
      .footer-contact {
        display: grid;
        gap: 0.7rem;
      }
      .footer-contact .mini {
        color: rgba(235, 243, 255, 0.75);
      }
      .footer-action {
        margin-top: 0.8rem;
      }
      .btn.small {
        padding: 0.82rem 1.1rem;
        font-size: 0.88rem;
        background: linear-gradient(135deg, #5d92ff 0%, #1d5fe9 100%);
        color: #ffffff;
        box-shadow: 0 16px 28px rgba(29, 95, 233, 0.28), 0 0 18px rgba(93, 146, 255, 0.2);
        border: 1px solid rgba(168, 195, 255, 0.75);
      }
      .btn.small:hover {
        transform: translateY(-2px);
      }
      .footer-bottom {
        max-width: 1200px;
        margin: 0 auto;
        padding: 1rem 2rem 2rem;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        color: rgba(235, 243, 255, 0.7);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
        font-size: 0.92rem;
      }
      .footer-bottom-links {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
      }
      .footer-bottom-links a {
        color: rgba(235, 243, 255, 0.7);
      }
      @media (max-width: 900px) {
        .hero, .showcase-section, .feature-band, .review-track, .stats-grid, .grid-2 { grid-template-columns: 1fr; }
        .section-header { display: block; }
        .site-footer-inner { grid-template-columns: 1fr 1fr; }
      }
      @media (max-width: 640px) {
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
        .hero, .showcase-section, .stats-section, .reviews-section, .feature-band { padding-left: 1rem; padding-right: 1rem; }
        .site-footer-inner {
          grid-template-columns: 1fr;
          padding-left: 1rem;
          padding-right: 1rem;
        }
        .footer-bottom {
          padding-left: 1rem;
          padding-right: 1rem;
        }
      }
      @media (max-width: 640px) {
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
        .hero, .showcase-section, .stats-section, .reviews-section, .feature-band { padding-left: 1rem; padding-right: 1rem; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span><span>CREDVEXA</span></div>
      <div class="header-actions">
        <a href="/login">Login</a>
        <a class="primary" href="/signup">Sign Up</a>
      </div>
    </header>

    <main>
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">Simple. Transparent. Responsible Lending.</p>
          <h1>Flexible Personal Loans, Simplified.</h1>
          <p class="hero-highlight">Borrow from ₹5,000 to ₹1,00,000</p>
          <div class="trust-points">
            <div class="trust-item">100% Digital Process</div>
            <div class="trust-item">Transparent Pricing</div>
            <div class="trust-item">Fast Disbursal</div>
          </div>
          <div class="cta-row">
            <a class="btn primary" href="/signup">Apply Now</a>
            <a class="btn secondary" href="/signup">Check Eligibility</a>
          </div>
          <p class="disclaimer">Demo / mock environment only. This is not a real approval, Aadhaar/PAN verification or live bank disbursal flow.</p>
        </div>

        <div class="hero-card">
          <div class="phone-badge">Demo Access</div>
          <h3>Start Your Application</h3>
          <p style="margin:0 0 1rem;color:var(--muted);">Create your account or log in to continue with a smooth, guided eligibility flow.</p>
          <a class="btn primary" href="/signup" style="width:100%;display:inline-flex;justify-content:center;">Create Account</a>
          <div class="mini-meta" style="margin-top:1rem;">
            <span>OTP verification</span>
            <span>Demo only</span>
          </div>
        </div>
      </section>

      <section class="feature-band">
        <div class="feature-card">
          <div class="feature-icon">⚡</div>
          <h3>Fastest Cash Disbursal</h3>
          <p>Minimal friction and quick decisions to help you move faster.</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">🔒</div>
          <h3>100% Digital Process</h3>
          <p>Online application, secure verification, and transparent updates.</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">📈</div>
          <h3>Flexible Tenure</h3>
          <p>Choose repayment durations that suit your monthly cash flow.</p>
        </div>
      </section>

      <section class="showcase-section">
        <div class="showcase-copy">
          <div class="eyebrow" style="text-align:center;">Trusted by modern borrowers</div>
          <h2>Everything you need, in one secure app.</h2>
          <div class="showcase-list">
            <div class="showcase-item">
              <div class="showcase-number">01</div>
              <div>
                <h4>Convenient Process</h4>
                <p>Apply, verify and track in minutes with a fully digital journey.</p>
              </div>
            </div>
            <div class="showcase-item">
              <div class="showcase-number">02</div>
              <div>
                <h4>Quick Approval</h4>
                <p>Smart checks and simple eligibility review move your application along faster.</p>
              </div>
            </div>
            <div class="showcase-item">
              <div class="showcase-number">03</div>
              <div>
                <h4>Secured Transaction</h4>
                <p>Your personal and financial information is protected through secure workflows.</p>
              </div>
            </div>
            <div class="showcase-item">
              <div class="showcase-number">04</div>
              <div>
                <h4>Flexible Tenure</h4>
                <p>Find a repayment structure aligned to your budget and lifestyle.</p>
              </div>
            </div>
          </div>
        </div>

        <div class="phone-mockup">
          <div class="phone-screen">
            <div class="screen-top">
              <span>Loan Dashboard</span>
              <span class="dot"></span>
            </div>
            <div class="screen-box primary-box">₹2,50,000<br /><small>Approved Limit</small></div>
            <div class="screen-box small-box">EMI ₹18,500</div>
            <div class="screen-box small-box">Status: Verified</div>
            <div class="screen-chart"><span></span><span></span><span></span><span></span></div>
          </div>
        </div>
      </section>

      <section class="stats-section">
        <div class="section-heading">
          <p class="eyebrow">Trusted by borrowers</p>
          <h2>Empowering Millions, One Loan at a Time</h2>
        </div>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-number" data-target="150000">0</div>
            <div class="stat-label">Trusted Users</div>
          </div>
          <div class="stat-card">
            <div class="stat-number" data-target="4200">0</div>
            <div class="stat-label">Total Disbursed</div>
          </div>
          <div class="stat-card">
            <div class="stat-number" data-target="9800">0</div>
            <div class="stat-label">Reviews</div>
          </div>
          <div class="stat-card">
            <div class="stat-number" data-target="28">0</div>
            <div class="stat-label">PAN India Presence</div>
          </div>
        </div>
      </section>

      <section id="calculator" class="calculator-card">
        <div class="section-header">
          <h2>EMI Calculator</h2>
          <p>Illustrative estimate only. Actual pricing and repayment terms may differ.</p>
        </div>
        <form id="emi-form" class="grid-2">
          <label>Loan Amount
            <select id="loanAmount">
              <option value="10000">₹10,000</option>
              <option value="25000">₹25,000</option>
              <option value="50000">₹50,000</option>
              <option value="100000" selected>₹1,00,000</option>
              <option value="200000">₹2,00,000</option>
              <option value="500000">₹5,00,000</option>
              <option value="1000000">₹10,00,000</option>
            </select>
          </label>
          <label>Interest Rate (%)
            <input id="interestRate" type="number" value="11.5" min="11.5" max="11.5" step="0.1" readonly />
          </label>
          <label>Tenure (months)
            <input id="tenure" type="number" value="12" min="1" max="60" />
          </label>
          <div class="result-box">
            <div class="result-item"><span>Monthly EMI</span><strong id="emiValue">₹0</strong></div>
            <div class="result-item"><span>Total Interest</span><strong id="interestValue">₹0</strong></div>
            <div class="result-item"><span>Total Repayment</span><strong id="repaymentValue">₹0</strong></div>
          </div>
        </form>
      </section>

      <section class="reviews-section">
        <div class="section-heading">
          <p class="eyebrow">Customer stories</p>
          <h2>People trust Credvexa for quick decisions and clear support.</h2>
        </div>
        <div class="reviews-slider">
          <div class="review-track">
            <article class="review-card">
              <div class="review-top">
                <div class="avatar">A</div>
                <div>
                  <h4>Ananya S.</h4>
                  <p>Bengaluru</p>
                </div>
              </div>
              <div class="stars">★★★★★</div>
              <p>“The process felt straightforward and secure. I completed everything online and got a clear status update without hassle.”</p>
            </article>
            <article class="review-card">
              <div class="review-top">
                <div class="avatar alt">R</div>
                <div>
                  <h4>Rohit M.</h4>
                  <p>Pune</p>
                </div>
              </div>
              <div class="stars">★★★★★</div>
              <p>“The product was easy to understand, and the response felt transparent. It gave me a lot more confidence before applying.”</p>
            </article>
            <article class="review-card">
              <div class="review-top">
                <div class="avatar">P</div>
                <div>
                  <h4>Priya K.</h4>
                  <p>Delhi</p>
                </div>
              </div>
              <div class="stars">★★★★★</div>
              <p>“I liked the clean UI and the digital verification flow. Everything was clear, quick, and professional.”</p>
            </article>
          </div>
        </div>
      </section>
    </main>

    <script>
      const loanAmount = document.getElementById('loanAmount');
      const interestRate = document.getElementById('interestRate');
      const tenure = document.getElementById('tenure');
      interestRate.value = '11.5';

      function updateEMI() {
        const principal = Number(loanAmount.value || 0);
        const rate = Number(interestRate.value || 11.5) / 12 / 100;
        const months = Number(tenure.value || 0);

        if (!principal || !months) {
          document.getElementById('emiValue').textContent = '₹0';
          document.getElementById('interestValue').textContent = '₹0';
          document.getElementById('repaymentValue').textContent = '₹0';
          return;
        }

        const emi = rate === 0
          ? principal / months
          : (principal * rate * Math.pow(1 + rate, months)) / (Math.pow(1 + rate, months) - 1);

        const totalRepayment = emi * months;
        const totalInterest = totalRepayment - principal;

        document.getElementById('emiValue').textContent = '₹' + emi.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        document.getElementById('interestValue').textContent = '₹' + totalInterest.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        document.getElementById('repaymentValue').textContent = '₹' + totalRepayment.toLocaleString('en-IN', { maximumFractionDigits: 0 });
      }

      [loanAmount, tenure].forEach((input) => input.addEventListener('input', updateEMI));
      updateEMI();
    </script>
    <footer class="site-footer">
      <div class="site-footer-inner">
        <div class="brand-block">
          <div class="brand"><span class="brand-mark">C</span><span>CREDVEXA</span></div>
          <p>Smart borrowing for modern life. We help you compare options, understand repayment plans, and move ahead with confidence through a secure digital workflow.</p>
          <div class="footer-badges">
            <span>ISO Ready</span>
            <span>Secure</span>
            <span>Fast Support</span>
          </div>
        </div>

        <div class="footer-section">
          <h4>Company</h4>
          <ul class="footer-links">
            <li><a href="/about">About us</a></li>
            <li><a href="/faq">FAQs</a></li>
            <li><a href="/blog">Blog</a></li>
            <li><a href="/calculator">EMI Calculator</a></li>
          </ul>
        </div>

        <div class="footer-section">
          <h4>Resources</h4>
          <ul class="footer-links">
            <li><a href="/apply">Apply now</a></li>
            <li><a href="/track">Track application</a></li>
            <li><a href="/dashboard">Dashboard</a></li>
            <li><a href="/contact">Contact</a></li>
          </ul>
        </div>

        <div class="footer-section">
          <h4>Need help?</h4>
          <div class="footer-contact">
            <div class="mini">help@credvexa.in</div>
            <div class="mini">77107-77742</div>
            <div class="mini">Mon-Sat • 9:00 AM to 7:00 PM</div>
            <div class="footer-action">
              <a class="btn primary small" href="/apply">Get started</a>
            </div>
          </div>
        </div>
      </div>

      <div class="footer-bottom">
        <div>© 2026 CREDVEXA. All rights reserved.</div>
        <div class="footer-bottom-links">
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
          <a href="/contact">Support</a>
        </div>
      </div>
    </footer>
  </body>
</html>
"""


APPLY_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Apply | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --danger: #D92D20;
        --warning: #D97706;
        --shadow-soft: 0 12px 32px rgba(11, 61, 145, 0.08);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
      }
      a { text-decoration: none; color: inherit; }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 40;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(228, 234, 242, 0.8);
      }
      .brand {
        display: inline-flex;
        align-items: center;
        gap: 0.7rem;
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        color: var(--primary);
      }
      .brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-size: 0.95rem;
      }
      nav {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
      }
      nav a {
        color: var(--text);
        font-weight: 600;
        padding: 0.4rem 0.65rem;
        border-radius: 999px;
      }
      nav a:hover {
        background: var(--primary-soft);
        color: var(--primary);
      }
      .logout-link {
        margin-left: 0.3rem;
        padding: 0.4rem 0.8rem;
        border-radius: 999px;
        background: rgba(11, 61, 145, 0.06);
        color: var(--primary);
        font-weight: 700;
      }
      .wrap { max-width: 1100px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .surface {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 28px;
        box-shadow: var(--shadow-soft);
        overflow: hidden;
      }
      .page-head {
        padding: 2rem 2rem 0.5rem;
      }
      .eyebrow {
        letter-spacing: 0.12em;
        font-size: 0.72rem;
        color: var(--secondary);
        font-weight: 800;
        text-transform: uppercase;
      }
      .page-head h1 {
        margin: 0.6rem 0 0.5rem;
        font-size: clamp(2rem, 4vw, 2.8rem);
      }
      .page-head p {
        margin: 0;
        color: var(--muted);
        line-height: 1.6;
      }
      form { padding: 1.5rem 2rem 2rem; }
      .resume-banner {
        margin: 1.2rem 2rem 0;
        background: linear-gradient(135deg, #edf5ff, #f3f8ff);
        border: 1px solid rgba(11, 61, 145, 0.12);
        border-radius: 14px;
        padding: 0.9rem 1rem;
        color: var(--primary);
        font-weight: 700;
        display: none;
      }
      .resume-banner.visible { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
      .resume-banner button {
        background: var(--primary);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.55rem 0.9rem;
        font-weight: 700;
        cursor: pointer;
      }
      .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.2rem; }
      .field { display: flex; flex-direction: column; gap: 0.45rem; }
      .field.full { grid-column: 1 / -1; }
      .field label {
        font-weight: 700;
        letter-spacing: 0.01em;
        font-size: 0.97rem;
      }
      .field input, .field select, .field textarea {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.9rem 1rem;
        font-size: 1rem;
        font-family: inherit;
        font-weight: 500;
        line-height: 1.5;
        background: #fff;
        color: var(--text);
      }
      .field textarea { min-height: 100px; resize: vertical; }
      .alert {
        background: #fff7e8;
        border: 1px solid #f4d8a1;
        border-radius: 14px;
        padding: 1rem 1.1rem;
        color: #8a5502;
        margin-top: 1rem;
      }
      .submit-row {
        display: flex;
        justify-content: flex-end;
        gap: 0.8rem;
        margin-top: 1.4rem;
      }
      .btn {
        border: none;
        border-radius: 12px;
        padding: 0.9rem 1.3rem;
        cursor: pointer;
        font-weight: 700;
      }
      .btn.primary {
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
      }
      .btn.secondary {
        background: #fff;
        color: var(--primary);
        border: 1px solid var(--border);
      }
      .result {
        margin-top: 1rem;
        padding: 1rem 1.1rem;
        border-radius: 14px;
        display: none;
      }
      .result.success {
        background: #ebfff5;
        border: 1px solid #bfead7;
        color: var(--success);
        display: block;
      }
      .result.error {
        background: #fff1f1;
        border: 1px solid #f4c6c6;
        color: var(--danger);
        display: block;
      }
      @media (max-width: 720px) {
        .grid { grid-template-columns: 1fr; }
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span><span>CREDVEXA</span></div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a class="logout-link" href="/logout">Logout</a>
      </nav>
    </header>

    <div class="wrap">
      <div class="surface page-head">
        <div class="eyebrow">Application form</div>
        <h1>Complete Your Application</h1>
        <p>Complete the form below. Final approval is subject to eligibility, verification, documentation and underwriting review. This does not guarantee a loan sanction.</p>
      </div>

      <div id="resumeBanner" class="resume-banner">
        <span>Resume your application</span>
        <button id="resumeBtn" type="button">Continue</button>
      </div>

      <div class="surface">
        <form id="loan-form">
          <div class="grid">
            <div class="field"><label for="first_name">First Name</label><input id="first_name" name="first_name" required /></div>
            <div class="field"><label for="middle_name">Middle Name / Second Name</label><input id="middle_name" name="middle_name" placeholder="Optional" /></div>
            <div class="field"><label for="last_name">Last Name</label><input id="last_name" name="last_name" required /></div>
            <div class="field"><label for="dob">Date of Birth</label><input id="dob" name="dob" type="date" required /></div>
            <div class="field"><label for="email">Email ID</label><input id="email" name="email" type="email" required /></div>
            <div class="field"><label for="mobile">Mobile Number</label><input id="mobile" name="mobile" required placeholder="9876543210" /></div>
            <div class="field"><label for="pan">PAN Number</label><input id="pan" name="pan" required placeholder="ABCDE1234F" /></div>
            <div class="field"><label for="aadhaar">Aadhaar Number</label><input id="aadhaar" name="aadhaar" required placeholder="123456789012" /></div>
            <div class="field"><label for="employment_type">Employment type</label>
              <select id="employment_type" name="employment_type">
                <option value="Salaried">Salaried</option>
                <option value="Self Employed">Self Employed</option>
                <option value="Business Owner">Business Owner</option>
                <option value="Professional">Professional</option>
              </select>
            </div>
            <div class="field">
              <label for="monthly_income">Monthly income</label>
              <select id="monthly_income" name="monthly_income" required>
                <option value="">Select range</option>
                <option value="15000">₹15,000 - ₹20,000</option>
                <option value="25000">₹25,000 - ₹40,000</option>
                <option value="50000">₹50,000 - ₹1,00,000</option>
              </select>
            </div>
            <div class="field"><label for="requested_amount">How Much Loan Do You Need?</label><input id="requested_amount" name="requested_amount" type="number" min="5000" max="100000" required /></div>
            <div class="field">
              <label for="tenure_months">Loan Tenure (Months)</label>
              <select id="tenure_months" name="tenure_months" required>
                <option value="">Select tenure</option>
                <option value="6">6 Months</option>
                <option value="12">12 Months</option>
                <option value="18">18 Months</option>
                <option value="24">24 Months</option>
                <option value="36">36 Months</option>
                <option value="48">48 Months</option>
                <option value="60">60 Months</option>
              </select>
            </div>
            <div class="field full">
              <label for="loan_purpose">Loan purpose</label>
              <select id="loan_purpose" name="loan_purpose" required>
                <option value="">Select purpose</option>
                <option value="Medical Emergency">Medical Emergency</option>
                <option value="Home Renovation">Home Renovation</option>
                <option value="Travel">Travel</option>
                <option value="Wedding">Wedding</option>
                <option value="Education">Education</option>
                <option value="Business Expansion">Business Expansion</option>
                <option value="Debt Consolidation">Debt Consolidation</option>
              </select>
            </div>
            <div class="field">
              <label for="city">City</label>
              <input id="city" name="city" list="cityOptions" placeholder="Select city" required />
              <datalist id="cityOptions"></datalist>
            </div>
            <div class="field">
              <label for="state">State</label>
              <input id="state" name="state" list="stateOptions" placeholder="Select state" required />
              <datalist id="stateOptions"></datalist>
            </div>
            <div class="field"><label for="pin_code">PIN code</label><input id="pin_code" name="pin_code" required maxlength="6" placeholder="6-digit PIN" /></div>
          </div>

          <div class="alert">Demo Mode – Please use test document details only. Do not enter real Aadhaar/PAN information. This is not a real KYC or final approval flow.</div>

          <div class="submit-row">
            <button type="button" class="btn secondary" onclick="location.href='/'">Back</button>
            <button type="submit" class="btn primary">Submit application</button>
          </div>
          <div id="result" class="result"></div>
        </form>
      </div>
    </div>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>

    <script>
      const form = document.getElementById('loan-form');
      const resultBox = document.getElementById('result');
      const resumeBanner = document.getElementById('resumeBanner');
      const resumeBtn = document.getElementById('resumeBtn');
      const DRAFT_KEY = 'credvexa_application_draft';
      const HOLD_MODAL_ID = 'holdApplicationModal';
      const pinCodeInput = document.getElementById('pin_code');
      const cityInput = document.getElementById('city');
      const stateInput = document.getElementById('state');
      const pinCodeMap = {
        '110001': ['New Delhi', 'Delhi'],
        '110002': ['New Delhi', 'Delhi'],
        '110003': ['New Delhi', 'Delhi'],
        '110011': ['Delhi', 'Delhi'],
        '110019': ['Delhi', 'Delhi'],
        '110020': ['Delhi', 'Delhi'],
        '110021': ['Delhi', 'Delhi'],
        '122001': ['Gurugram', 'Haryana'],
        '122002': ['Gurugram', 'Haryana'],
        '122003': ['Gurugram', 'Haryana'],
        '121001': ['Faridabad', 'Haryana'],
        '121002': ['Faridabad', 'Haryana'],
        '121006': ['Faridabad', 'Haryana'],
        '201301': ['Noida', 'Uttar Pradesh'],
        '201302': ['Noida', 'Uttar Pradesh'],
        '201303': ['Noida', 'Uttar Pradesh'],
        '201005': ['Ghaziabad', 'Uttar Pradesh'],
        '201006': ['Ghaziabad', 'Uttar Pradesh'],
        '201010': ['Ghaziabad', 'Uttar Pradesh'],
        '226001': ['Lucknow', 'Uttar Pradesh'],
        '226002': ['Lucknow', 'Uttar Pradesh'],
        '226010': ['Lucknow', 'Uttar Pradesh'],
        '208001': ['Kanpur', 'Uttar Pradesh'],
        '208002': ['Kanpur', 'Uttar Pradesh'],
        '208016': ['Kanpur', 'Uttar Pradesh'],
        '302001': ['Jaipur', 'Rajasthan'],
        '302002': ['Jaipur', 'Rajasthan'],
        '302005': ['Jaipur', 'Rajasthan'],
        '332001': ['Jaipur', 'Rajasthan'],
        '380001': ['Ahmedabad', 'Gujarat'],
        '380002': ['Ahmedabad', 'Gujarat'],
        '380015': ['Ahmedabad', 'Gujarat'],
        '395001': ['Surat', 'Gujarat'],
        '395002': ['Surat', 'Gujarat'],
        '395006': ['Surat', 'Gujarat'],
        '400001': ['Mumbai', 'Maharashtra'],
        '400002': ['Mumbai', 'Maharashtra'],
        '400003': ['Mumbai', 'Maharashtra'],
        '411001': ['Pune', 'Maharashtra'],
        '411002': ['Pune', 'Maharashtra'],
        '411005': ['Pune', 'Maharashtra'],
        '410001': ['Nagpur', 'Maharashtra'],
        '410002': ['Nagpur', 'Maharashtra'],
        '440001': ['Nagpur', 'Maharashtra'],
        '440002': ['Nagpur', 'Maharashtra'],
        '412001': ['Satara', 'Maharashtra'],
        '412002': ['Satara', 'Maharashtra'],
        '413001': ['Kolhapur', 'Maharashtra'],
        '413002': ['Kolhapur', 'Maharashtra'],
        '500001': ['Hyderabad', 'Telangana'],
        '500002': ['Hyderabad', 'Telangana'],
        '500003': ['Hyderabad', 'Telangana'],
        '500081': ['Hyderabad', 'Telangana'],
        '500082': ['Hyderabad', 'Telangana'],
        '500084': ['Hyderabad', 'Telangana'],
        '560001': ['Bengaluru', 'Karnataka'],
        '560002': ['Bengaluru', 'Karnataka'],
        '560068': ['Bengaluru', 'Karnataka'],
        '560085': ['Bengaluru', 'Karnataka'],
        '560095': ['Bengaluru', 'Karnataka'],
        '560103': ['Bengaluru', 'Karnataka'],
        '560106': ['Bengaluru', 'Karnataka'],
        '560114': ['Bengaluru', 'Karnataka'],
        '600001': ['Chennai', 'Tamil Nadu'],
        '600002': ['Chennai', 'Tamil Nadu'],
        '600003': ['Chennai', 'Tamil Nadu'],
        '600090': ['Chennai', 'Tamil Nadu'],
        '600100': ['Chennai', 'Tamil Nadu'],
        '600119': ['Chennai', 'Tamil Nadu'],
        '700001': ['Kolkata', 'West Bengal'],
        '700002': ['Kolkata', 'West Bengal'],
        '700006': ['Kolkata', 'West Bengal'],
        '700010': ['Kolkata', 'West Bengal'],
        '800001': ['Patna', 'Bihar'],
        '800002': ['Patna', 'Bihar'],
        '800020': ['Patna', 'Bihar'],
        '826001': ['Dhanbad', 'Jharkhand'],
        '826002': ['Dhanbad', 'Jharkhand'],
        '831001': ['Ranchi', 'Jharkhand'],
        '831002': ['Ranchi', 'Jharkhand'],
        '492001': ['Raipur', 'Chhattisgarh'],
        '492002': ['Raipur', 'Chhattisgarh'],
        '490001': ['Raipur', 'Chhattisgarh'],
        '431001': ['Bhopal', 'Madhya Pradesh'],
        '431002': ['Bhopal', 'Madhya Pradesh'],
        '462001': ['Bhopal', 'Madhya Pradesh'],
        '462002': ['Bhopal', 'Madhya Pradesh'],
        '452001': ['Indore', 'Madhya Pradesh'],
        '452002': ['Indore', 'Madhya Pradesh'],
        '452010': ['Indore', 'Madhya Pradesh'],
        '751001': ['Bhubaneswar', 'Odisha'],
        '751002': ['Bhubaneswar', 'Odisha'],
        '751015': ['Bhubaneswar', 'Odisha'],
        '751024': ['Bhubaneswar', 'Odisha'],
        '160001': ['Chandigarh', 'Chandigarh'],
        '160002': ['Chandigarh', 'Chandigarh'],
        '160022': ['Chandigarh', 'Chandigarh'],
        '141001': ['Ludhiana', 'Punjab'],
        '141002': ['Ludhiana', 'Punjab'],
        '180001': ['Jammu', 'Jammu and Kashmir'],
        '180002': ['Jammu', 'Jammu and Kashmir'],
        '682001': ['Kochi', 'Kerala'],
        '682002': ['Kochi', 'Kerala'],
        '560030': ['Bengaluru', 'Karnataka'],
        '560035': ['Bengaluru', 'Karnataka'],
        '560040': ['Bengaluru', 'Karnataka']
      };

      function populateLocationSelects() {
        const pin = pinCodeInput.value.trim();
        const allStates = [...new Set(Object.values(pinCodeMap).map(([, state]) => state))].sort();
        const stateOptions = document.getElementById('stateOptions');
        const cityOptions = document.getElementById('cityOptions');
        stateOptions.innerHTML = allStates.map((state) => `<option value="${state}"></option>`).join('');

        if (!pin || pin.length < 6) {
          cityOptions.innerHTML = '';
          stateInput.value = '';
          cityInput.value = '';
          return;
        }

        const entry = pinCodeMap[pin];
        if (!entry) {
          cityOptions.innerHTML = '';
          stateInput.value = '';
          cityInput.value = '';
          return;
        }

        const matchingCities = [...new Set(
          Object.entries(pinCodeMap)
            .filter(([, [, state]]) => state === entry[1])
            .map(([, [city]]) => city)
        )].sort();

        cityOptions.innerHTML = matchingCities.map((city) => `<option value="${city}"></option>`).join('');
        stateInput.value = entry[1];
        cityInput.value = entry[0];
      }

      function fillLocationFromPin() {
        populateLocationSelects();
      }

      function saveDraft() {
        const payload = Object.fromEntries(new FormData(form).entries());
        localStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
      }

      function restoreDraft() {
        const draft = localStorage.getItem(DRAFT_KEY);
        if (!draft) return;
        try {
          const parsed = JSON.parse(draft);
          Object.entries(parsed).forEach(([key, value]) => {
            const element = form.elements.namedItem(key);
            if (element) element.value = value;
          });
          resumeBanner.classList.add('visible');
        } catch (error) {
          localStorage.removeItem(DRAFT_KEY);
        }
      }

      function clearDraft() {
        localStorage.removeItem(DRAFT_KEY);
      }

      function showHoldModal() {
        let modal = document.getElementById(HOLD_MODAL_ID);
        if (!modal) {
          modal = document.createElement('div');
          modal.id = HOLD_MODAL_ID;
          modal.style.position = 'fixed';
          modal.style.top = '0';
          modal.style.left = '0';
          modal.style.right = '0';
          modal.style.bottom = '0';
          modal.style.background = 'rgba(9, 17, 34, 0.42)';
          modal.style.display = 'flex';
          modal.style.alignItems = 'center';
          modal.style.justifyContent = 'center';
          modal.style.zIndex = '1000';
          modal.innerHTML = `
            <div style="background:#fff;border-radius:18px;max-width:480px;width:calc(100% - 2rem);padding:1.5rem 1.5rem 1rem;border:1px solid #e4eaf2;box-shadow:0 12px 32px rgba(11, 61, 145, 0.16);">
              <h3 style="margin:0 0 0.75rem;font-size:1.6rem;">Your Application Is On Hold</h3>
              <p style="margin:0 0 1rem;color:#667085;line-height:1.6;">Your application is currently in progress. Would you like to keep it on hold or cancel your application?</p>
              <div style="display:flex;gap:0.75rem;flex-wrap:wrap;justify-content:flex-end;">
                <button id="keepOnHoldBtn" type="button" style="background:#eef5ff;color:#0B3D91;border:none;border-radius:12px;padding:0.8rem 1.1rem;font-weight:700;cursor:pointer;">Keep Application On Hold</button>
                <button id="cancelAppBtn" type="button" style="background:#D92D20;color:#fff;border:none;border-radius:12px;padding:0.8rem 1.1rem;font-weight:700;cursor:pointer;">Cancel Application</button>
              </div>
            </div>
          `;
          document.body.appendChild(modal);

          document.getElementById('keepOnHoldBtn').addEventListener('click', () => {
            saveDraft();
            modal.remove();
            window.location.href = '/';
          });

          document.getElementById('cancelAppBtn').addEventListener('click', () => {
            clearDraft();
            modal.remove();
            window.location.href = '/';
          });
        }
        modal.style.display = 'flex';
      }

      pinCodeInput.addEventListener('input', fillLocationFromPin);

      form.addEventListener('input', saveDraft);
      form.addEventListener('change', saveDraft);
      resumeBtn.addEventListener('click', () => {
        resumeBanner.classList.remove('visible');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });

      fillLocationFromPin();

      document.querySelectorAll('a[href="/"]').forEach((link) => {
        link.addEventListener('click', (event) => {
          const hasProgress = Boolean(localStorage.getItem(DRAFT_KEY));
          if (hasProgress) {
            event.preventDefault();
            showHoldModal();
          }
        });
      });

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = Object.fromEntries(new FormData(form).entries());
        const firstName = (formData.first_name || '').trim();
        const middleName = (formData.middle_name || '').trim();
        const lastName = (formData.last_name || '').trim();
        const fullName = [firstName, middleName, lastName].filter(Boolean).join(' ');
        const payload = { ...formData, full_name: fullName };
        delete payload.first_name;
        delete payload.middle_name;
        delete payload.last_name;
        resultBox.className = 'result';
        resultBox.textContent = '';

        try {
          const response = await fetch('/api/applications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Unable to submit application.');

          clearDraft();
          resultBox.classList.add('success');
          resultBox.innerHTML = `Application submitted successfully.<br>Application ID: <strong>${data.application_id}</strong><br>Status: <strong>${data.status}</strong><br>Offer Amount: <strong>₹${Number(data.offer_amount).toLocaleString('en-IN')}</strong>`;
          form.reset();
          setTimeout(() => {
            window.location.href = data.next_url || '/pre-approved-loan';
          }, 1000);
        } catch (error) {
          resultBox.classList.add('error');
          resultBox.textContent = error.message;
        }
      });

      restoreDraft();
    </script>
  </body>
</html>
"""


TRACK_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Track | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --danger: #D92D20;
        --shadow-soft: 0 12px 32px rgba(11, 61, 145, 0.08);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
      }
      a { text-decoration: none; color: inherit; }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 40;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(228, 234, 242, 0.8);
      }
      .brand {
        display: inline-flex;
        align-items: center;
        gap: 0.7rem;
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        color: var(--primary);
      }
      .brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-size: 0.95rem;
      }
      nav {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
      }
      nav a {
        color: var(--text);
        font-weight: 600;
        padding: 0.4rem 0.65rem;
        border-radius: 999px;
      }
      nav a:hover {
        background: var(--primary-soft);
        color: var(--primary);
      }
      .wrapper { max-width: 900px; margin: 3rem auto; padding: 0 1.25rem; }
      .surface {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 28px;
        box-shadow: var(--shadow-soft);
        padding: 2rem;
      }
      h1 { margin-top: 0; }
      form {
        display: grid;
        grid-template-columns: 1fr 1fr auto;
        gap: 1rem;
        align-items: end;
      }
      label {
        display: block;
        font-weight: 700;
        margin-bottom: 0.35rem;
      }
      input {
        width: 100%;
        padding: 0.9rem 1rem;
        border: 1px solid var(--border);
        border-radius: 12px;
      }
      button {
        border: none;
        border-radius: 12px;
        padding: 0.9rem 1.2rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-weight: 700;
        cursor: pointer;
      }
      .result {
        margin-top: 1.4rem;
        padding: 1rem 1.1rem;
        border-radius: 14px;
        display: none;
      }
      .result.success {
        display: block;
        background: #ebfff5;
        border: 1px solid #bfead7;
        color: var(--success);
      }
      .result.error {
        display: block;
        background: #fff1f1;
        border: 1px solid #f4c6c6;
        color: var(--danger);
      }
      .row {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.9rem;
      }
      @media (max-width: 700px) {
        form { grid-template-columns: 1fr; }
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span><span>CREDVEXA</span></div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <div class="wrapper">
      <div class="surface">
        <h1>Track your application</h1>
        <form id="track-form">
          <div>
            <label>Application ID</label>
            <input id="application_id" required />
          </div>
          <div>
            <label>Mobile number</label>
            <input id="mobile" required />
          </div>
          <button type="submit">Check status</button>
        </form>

        <div id="track-result" class="result"></div>
      </div>
    </div>

    <script>
      const trackForm = document.getElementById('track-form');
      const resultBox = document.getElementById('track-result');

      trackForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const appId = document.getElementById('application_id').value.trim();
        const mobile = document.getElementById('mobile').value.trim();
        resultBox.className = 'result';
        resultBox.textContent = '';

        try {
          const response = await fetch(`/api/track/${encodeURIComponent(appId)}/${encodeURIComponent(mobile)}`);
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Application not found.');

          resultBox.classList.add('success');
          resultBox.innerHTML = `
            <div class="row">
              <div><strong>Application ID</strong><br>${data.application_id}</div>
              <div><strong>Name</strong><br>${data.full_name}</div>
              <div><strong>Status</strong><br>${data.status}</div>
              <div><strong>EMI</strong><br>₹${Number(data.emi || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</div>
              <div><strong>Purpose</strong><br>${data.loan_purpose}</div>
              <div><strong>Updated</strong><br>${data.updated_at}</div>
            </div>
            <p style="margin-top:16px;">${data.note}</p>
          `;
        } catch (error) {
          resultBox.classList.add('error');
          resultBox.textContent = error.message;
        }
      });
    </script>
  </body>
</html>
"""


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Dashboard | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --warning: #D97706;
        --danger: #D92D20;
        --shadow-soft: 0 12px 32px rgba(11, 61, 145, 0.08);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
      }
      a { text-decoration: none; color: inherit; }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 40;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(228, 234, 242, 0.8);
      }
      .brand {
        display: inline-flex;
        align-items: center;
        gap: 0.7rem;
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        color: var(--primary);
      }
      .brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        font-size: 0.95rem;
      }
      nav {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
      }
      nav a {
        color: var(--text);
        font-weight: 600;
        padding: 0.4rem 0.65rem;
        border-radius: 999px;
      }
      nav a:hover {
        background: var(--primary-soft);
        color: var(--primary);
      }
      .wrapper { max-width: 1000px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .surface {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 28px;
        box-shadow: var(--shadow-soft);
        padding: 2rem;
      }
      h1 { margin-top: 0; }
      .summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
      }
      .stat {
        background: var(--primary-soft);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 1.2rem;
      }
      .stat span { color: var(--muted); display: block; }
      .stat strong {
        display: block;
        font-size: 1.6rem;
        color: var(--primary);
        margin-top: 0.35rem;
      }
      .list {
        margin-top: 1.5rem;
        display: grid;
        gap: 0.8rem;
      }
      .item {
        border: 1px solid var(--border);
        border-radius: 16px;
        background: #fafcff;
        padding: 1rem 1.1rem;
      }
      .status {
        font-weight: 700;
        margin-top: 0.25rem;
      }
      .status.under_review { color: var(--warning); }
      .status.approved { color: var(--success); }
      .status.rejected { color: var(--danger); }
      .status.pending { color: var(--muted); }
      @media (max-width: 700px) {
        .summary { grid-template-columns: 1fr; }
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span><span>CREDVEXA</span></div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <div class="wrapper">
      <div class="surface">
        <h1>CREDVEXA dashboard</h1>
        <div class="summary">
          <div class="stat"><span>Total applications</span><strong id="total">0</strong></div>
          <div class="stat"><span>Under review</span><strong id="underReview">0</strong></div>
          <div class="stat"><span>Approved</span><strong id="approved">0</strong></div>
        </div>
        <div class="list" id="app-list"></div>
      </div>
    </div>

    <script>
      async function loadDashboard() {
        const response = await fetch('/api/dashboard');
        const data = await response.json();
        document.getElementById('total').textContent = data.total;
        document.getElementById('underReview').textContent = data.under_review;
        document.getElementById('approved').textContent = data.approved;

        const list = document.getElementById('app-list');
        list.innerHTML = '';

        data.applications.forEach((item) => {
          const div = document.createElement('div');
          div.className = 'item';
          div.innerHTML = `
            <div><strong>${item.full_name}</strong> - ${item.application_id}</div>
            <div>Email: ${item.email} | Mobile: ${item.mobile}</div>
            <div>Loan: ₹${Number(item.requested_amount || 0).toLocaleString('en-IN')} | EMI: ₹${Number(item.emi || 0).toLocaleString('en-IN')}</div>
            <div class="status ${item.status.toLowerCase().replace(/[\\s]+/g, '_')}">${item.status}</div>
            <div>${item.note}</div>
          `;
          list.appendChild(div);
        });
      }
      loadDashboard();
    </script>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


ABOUT_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>About | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --warning: #D97706;
        --danger: #D92D20;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--text);
      }
      a { text-decoration: none; color: inherit; }
      .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        border-bottom: 1px solid rgba(228, 234, 242, 0.8);
      }
      .brand {
        display: inline-flex;
        align-items: center;
        gap: 0.7rem;
        font-size: 1.45rem;
        font-weight: 800;
        color: var(--primary);
      }
      .brand-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: white;
      }
      nav {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
      }
      nav a {
        color: var(--text);
        font-weight: 600;
        padding: 0.4rem 0.65rem;
        border-radius: 999px;
      }
      nav a:hover {
        background: var(--primary-soft);
        color: var(--primary);
      }
      .container { max-width: 1100px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 28px;
        padding: 2rem;
        box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08);
      }
      h1 { margin-top: 0; font-size: clamp(2rem, 4vw, 3rem); }
      .grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1.2rem;
        margin-top: 1.5rem;
      }
      .info {
        background: var(--primary-soft);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 1.2rem;
      }
      .info h3 { margin-top: 0; }
      .info p, .lead { color: var(--muted); line-height: 1.7; }
      @media (max-width: 700px) {
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
        .grid { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <p class="lead">About CREDVEXA</p>
        <h1>Built for a clear and digital borrowing journey.</h1>
        <p class="lead">CREDVEXA helps customers understand loan options, submit applications, track progress, and stay informed about eligibility and documentation requirements. We focus on transparency, clarity, and responsible digital lending practices.</p>
        <div class="grid">
          <div class="info">
            <h3>Our approach</h3>
            <p>We keep the process simple, secure, and easy to understand. Applicants can apply online, review their details, and receive status updates without confusion.</p>
          </div>
          <div class="info">
            <h3>What we do</h3>
            <p>We provide a user-friendly loan application flow, eligibility screening, document review guidance, and clear communication around approval criteria.</p>
          </div>
          <div class="info">
            <h3>Responsible lending</h3>
            <p>Final loan approval depends on verification, policy review, eligibility checks, and documentation. There is no guaranteed approval or guarantee of disbursal.</p>
          </div>
          <div class="info">
            <h3>Security</h3>
            <p>We aim to handle customer data with care, with encrypted and privacy-conscious workflows and clear consent-based communication.</p>
          </div>
        </div>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


CONTACT_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Contact | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 900px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      .row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
      .info { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 18px; padding: 1.2rem; }
      .info h3 { margin-top: 0; }
      .info p { margin: 0.3rem 0 0; color: var(--muted); }
      @media (max-width: 700px) { .row { grid-template-columns: 1fr; } .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Contact us</h1>
        <p>Need help with your application or want to understand the process better? We are here to guide you.</p>
        <div class="row">
          <div class="info">
            <h3>Email</h3>
            <p>help@credvexa.in</p>
          </div>
          <div class="info">
            <h3>Phone</h3>
            <p>77107-77742</p>
          </div>
          <div class="info">
            <h3>Hours</h3>
            <p>Mon - Sat, 9:00 AM to 7:00 PM</p>
          </div>
          <div class="info">
            <h3>Office</h3>
            <p>Business District, Bengaluru, India</p>
          </div>
        </div>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


PRIVACY_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Privacy | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 1000px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      p, li { color: var(--muted); line-height: 1.7; }
      ul { padding-left: 1.2rem; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Privacy policy</h1>
        <p>We respect your privacy and handle personal information responsibly. The purpose of collecting data is to process your loan application, verify identity, assess eligibility, and communicate status updates.</p>
        <ul>
          <li>We collect information required for application processing, eligibility review, and compliance checks.</li>
          <li>We use secure systems and access controls to reduce the risk of unauthorized access.</li>
          <li>Information may be shared only with authorized verification or processing partners as needed for the application workflow.</li>
          <li>Applicants have the right to request clarification or correction of personal information related to the application.</li>
        </ul>
        <p>Final approval remains subject to verification, documentation review, policy rules, and lender criteria.</p>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


TERMS_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Terms | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 1000px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      p, li { color: var(--muted); line-height: 1.7; }
      ul { padding-left: 1.2rem; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Terms and conditions</h1>
        <p>These terms explain how the CREDVEXA digital application workflow is intended to operate. The platform is designed to help users submit applications, review loan information, and track status updates.</p>
        <ul>
          <li>Applications are subject to eligibility review, document verification, and underwriting assessment.</li>
          <li>There is no promise of loan approval, sanction, or disbursement by completing the application form.</li>
          <li>Any processing fee or disclosure shown in the flow is illustrative and must be confirmed in the final formal agreement where applicable.</li>
          <li>We may update these terms to reflect operational, legal, or compliance requirements.</li>
        </ul>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


FAQ_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>FAQs | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 1100px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      .faq-item { border: 1px solid var(--border); border-radius: 18px; background: var(--primary-soft); padding: 1.25rem; margin-bottom: 1rem; }
      .faq-item h3 { margin: 0 0 0.5rem; }
      .faq-item p { margin: 0; color: var(--muted); line-height: 1.7; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Frequently asked questions</h1>
        <div class="faq-item">
          <h3>How do I apply?</h3>
          <p>Visit the Apply page, fill in your personal and income details, and complete the digital application form.</p>
        </div>
        <div class="faq-item">
          <h3>Is approval guaranteed?</h3>
          <p>No. Final decisions depend on eligibility, verification, and underwriting review. We do not guarantee approval.</p>
        </div>
        <div class="faq-item">
          <h3>What is the interest rate?</h3>
          <p>Illustrative EMI estimates use a fixed rate of 11.5% per annum for this demo experience.</p>
        </div>
        <div class="faq-item">
          <h3>How can I track my application?</h3>
          <p>Use the Track page and enter your mobile number or application reference to view status updates.</p>
        </div>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


BLOG_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Blog | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 1100px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1.2rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 1.5rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      .tag { display: inline-block; background: var(--primary-soft); color: var(--primary); border-radius: 999px; padding: 0.35rem 0.7rem; font-size: 0.74rem; font-weight: 700; margin-bottom: 0.8rem; }
      h1 { margin-top: 0; }
      h3 { margin: 0 0 0.7rem; }
      p { color: var(--muted); line-height: 1.7; }
      @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
      </nav>
    </header>

    <main class="container">
      <h1>Insights & advice</h1>
      <div class="grid">
        <article class="card">
          <div class="tag">Borrowing</div>
          <h3>How to plan your loan before you apply</h3>
          <p>Review your monthly cash flow, avoid overstretching, and compare the tenure options that fit your repayment comfort.</p>
        </article>
        <article class="card">
          <div class="tag">Finance</div>
          <h3>Understanding EMI planning in simple terms</h3>
          <p>EMI is the monthly repayment amount based on your principal, duration, and rate. Using a fixed rate helps you estimate better.</p>
        </article>
        <article class="card">
          <div class="tag">Checklist</div>
          <h3>Documents that make the process smoother</h3>
          <p>Keep identity, address, income, and bank records ready to help reduce delays during verification and review.</p>
        </article>
      </div>
    </main>

    <footer class="site-footer">
      <div class="site-footer-inner">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
      </div>
    </footer>
  </body>
</html>
"""


CALCULATOR_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>EMI Calculator | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228, 234, 242, 0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 900px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
      label { display: grid; gap: 0.4rem; font-weight: 600; }
      input, select { border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1rem; background: #fff; color: var(--text); }
      .result-box { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 18px; padding: 1rem; display: grid; gap: 0.8rem; }
      .result-item { display: flex; justify-content: space-between; gap: 1rem; font-weight: 700; }
      h1 { margin-top: 0; }
      @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/apply">Apply</a>
        <a href="/faq">FAQs</a>
        <a href="/blog">Blog</a>
        <a href="/calculator">Calculator</a>
        <a href="/contact">Contact</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>EMI Calculator</h1>
        <p>Illustrative estimate only. The working rate used in this demo is fixed at 11.5% p.a.</p>
        <form class="grid" id="emi-form-page">
          <label>Loan Amount
            <select id="loanAmountPage">
              <option value="10000">₹10,000</option>
              <option value="25000">₹25,000</option>
              <option value="50000">₹50,000</option>
              <option value="100000" selected>₹1,00,000</option>
              <option value="200000">₹2,00,000</option>
              <option value="500000">₹5,00,000</option>
              <option value="1000000">₹10,00,000</option>
            </select>
          </label>
          <label>Interest Rate (%)
            <input id="interestRatePage" type="number" value="11.5" min="11.5" max="11.5" step="0.1" readonly />
          </label>
          <label>Tenure (months)
            <input id="tenurePage" type="number" value="12" min="1" max="60" />
          </label>
          <div class="result-box">
            <div class="result-item"><span>Monthly EMI</span><strong id="emiValuePage">₹0</strong></div>
            <div class="result-item"><span>Total Interest</span><strong id="interestValuePage">₹0</strong></div>
            <div class="result-item"><span>Total Repayment</span><strong id="repaymentValuePage">₹0</strong></div>
          </div>
        </form>
      </div>
    </main>

    <script>
      const loanAmountPage = document.getElementById('loanAmountPage');
      const tenurePage = document.getElementById('tenurePage');
      const interestRatePage = document.getElementById('interestRatePage');
      interestRatePage.value = '11.5';

      function updatePageEMI() {
        const principal = Number(loanAmountPage.value || 0);
        const months = Number(tenurePage.value || 0);
        const rate = Number(interestRatePage.value || 11.5) / 12 / 100;

        if (!principal || !months) {
          document.getElementById('emiValuePage').textContent = '₹0';
          document.getElementById('interestValuePage').textContent = '₹0';
          document.getElementById('repaymentValuePage').textContent = '₹0';
          return;
        }

        const emi = rate === 0
          ? principal / months
          : (principal * rate * Math.pow(1 + rate, months)) / (Math.pow(1 + rate, months) - 1);

        const totalRepayment = emi * months;
        const totalInterest = totalRepayment - principal;

        document.getElementById('emiValuePage').textContent = '₹' + emi.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        document.getElementById('interestValuePage').textContent = '₹' + totalInterest.toLocaleString('en-IN', { maximumFractionDigits: 0 });
        document.getElementById('repaymentValuePage').textContent = '₹' + totalRepayment.toLocaleString('en-IN', { maximumFractionDigits: 0 });
      }

      [loanAmountPage, tenurePage].forEach((input) => input.addEventListener('input', updatePageEMI));
      updatePageEMI();
    </script>
  </body>
</html>
"""

PRE_APPROVED_OFFER = {
    "loan_amount": 50000,
    "offer_amount": 50000,
    "loan_limit_min": 10000,
    "loan_limit_max": 100000,
    "max_tenure_months": 60,
    "rate": 11.5,
}
REJECTION_REASONS = [
    "Your application was rejected due to payment behavior and verification concerns.",
    "We could not proceed due to incomplete or inconsistent KYC and payment checks.",
    "The application was rejected because of behavioral risk and document irregularities.",
    "This application was not approved due to a failed verification or policy review.",
    "The payment and application workflow did not meet the required review thresholds.",
]


def generate_rejection_reason():
    return random.choice(REJECTION_REASONS)


def find_candidate_rejected_record(mobile=None, pan=None, aadhaar=None):
    records = load_applications()
    for record in reversed(records):
        if str(record.get("status", "")).upper() != "REJECTED":
            continue
        if mobile and str(record.get("mobile", "")).strip() == str(mobile).strip():
            return record
        if pan and str(record.get("pan", "")).strip().upper() == str(pan).strip().upper():
            return record
        if aadhaar and str(record.get("aadhaar", "")).strip() == str(aadhaar).strip():
            return record
    return None


def get_reapply_block(mobile=None, pan=None, aadhaar=None):
    record = find_candidate_rejected_record(mobile=mobile, pan=pan, aadhaar=aadhaar)
    if not record:
        return {"blocked": False, "days_remaining": 0, "reason": ""}
    rejected_at = str(record.get("rejected_at", "")).strip()
    try:
        rejected_dt = datetime.strptime(rejected_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        rejected_dt = datetime.now()
    elapsed = (datetime.now() - rejected_dt).days
    days_remaining = max(0, 30 - elapsed)
    if elapsed < 30:
        return {
            "blocked": True,
            "days_remaining": days_remaining,
            "reason": str(record.get("rejection_reason") or generate_rejection_reason()),
        }
    return {"blocked": False, "days_remaining": 0, "reason": ""}


def get_preapproved_offer_for_candidate(mobile=None, pan=None, aadhaar=None):
    records = load_applications()
    for record in reversed(records):
        record_pan = str(record.get("pan", "")).strip().upper()
        record_aadhaar = str(record.get("aadhaar", "")).strip()
        record_mobile = str(record.get("mobile", "")).strip()
        if mobile and record_mobile == str(mobile).strip():
            return {
                "offer_amount": 50000,
                "loan_limit_min": 10000,
                "loan_limit_max": 100000,
                "max_tenure_months": 60,
                "rate": 11.5,
                "is_existing_customer": True,
            }
        if pan and record_pan == str(pan).strip().upper():
            return {
                "offer_amount": 50000,
                "loan_limit_min": 10000,
                "loan_limit_max": 100000,
                "max_tenure_months": 60,
                "rate": 11.5,
                "is_existing_customer": True,
            }
        if aadhaar and record_aadhaar == str(aadhaar).strip():
            return {
                "offer_amount": 50000,
                "loan_limit_min": 10000,
                "loan_limit_max": 100000,
                "max_tenure_months": 60,
                "rate": 11.5,
                "is_existing_customer": True,
            }
    return dict(PRE_APPROVED_OFFER, is_existing_customer=False)


SIGNUP_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Sign Up | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --success: #16834B; --error: #D92D20; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: linear-gradient(180deg, #f6f9fd 0%, #eef5ff 100%); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228,234,242,0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      .header-actions { display: flex; gap: 0.75rem; }
      .header-actions a { padding: 0.7rem 1rem; border-radius: 999px; border: 1px solid var(--border); background: #fff; color: var(--text); font-weight: 700; }
      .header-actions .primary { background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; border-color: transparent; }
      .container { max-width: 520px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      .notice { color: var(--muted); margin-bottom: 1rem; }
      label { display: grid; gap: 0.4rem; font-weight: 600; margin-bottom: 0.8rem; }
      input { width: 100%; border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1rem; margin-top: 0.25rem; background: #fff; color: var(--text); }
      button { width: 100%; border: none; border-radius: 12px; padding: 0.95rem 1rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; font-weight: 700; cursor: pointer; }
      .status { display: none; margin-top: 1rem; padding: 0.85rem 1rem; border-radius: 12px; font-weight: 600; }
      .status.success { display: block; background: #ebf9f1; border: 1px solid rgba(22, 131, 75, 0.2); color: var(--success); }
      .status.error { display: block; background: #fff2f0; border: 1px solid rgba(217,45,32,0.2); color: var(--error); }
      .meta { margin-top: 0.85rem; color: var(--muted); font-size: 0.92rem; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <div class="header-actions">
        <a href="/login">Login</a>
        <a class="primary" href="/signup">Sign Up</a>
      </div>
    </header>

    <main class="container">
      <div class="card">
        <h1>Sign Up</h1>
        <p class="notice">Create your demo account to begin the Credvexa loan journey with a secure, guided flow.</p>
        <form id="signupForm">
          <label>Full Name
            <input name="full_name" type="text" placeholder="Enter full name" required />
          </label>
          <label>Email ID
            <input name="email" type="email" placeholder="you@example.com" required />
          </label>
          <label>Mobile Number
            <input name="mobile" type="tel" maxlength="10" placeholder="10-digit mobile number" required />
          </label>
          <label>Password
            <input name="password" type="password" placeholder="Create a password" required />
          </label>
          <button type="submit">Create Account</button>
        </form>
        <div id="statusBox" class="status"></div>
        <div class="meta">Demo environment: use test data only. Real Aadhaar, PAN or KYC are not part of this mock experience.</div>
      </div>
    </main>

    <script>
      const form = document.getElementById('signupForm');
      const statusBox = document.getElementById('statusBox');

      function setStatus(message, kind) {
        statusBox.className = `status ${kind}`;
        statusBox.textContent = message;
      }

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        try {
          const response = await fetch('/api/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Unable to create account.');

          setStatus('Account created successfully. Please verify your mobile number to continue.', 'success');
          form.reset();
          setTimeout(() => {
            window.location.href = `/verify-login?mobile=${encodeURIComponent(payload.mobile)}`;
          }, 1200);
        } catch (error) {
          setStatus(error.message, 'error');
        }
      });
    </script>
  </body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Login | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --success: #16834B; --error: #D92D20; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: linear-gradient(180deg, #f6f9fd 0%, #eef5ff 100%); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228,234,242,0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      .header-actions { display: flex; gap: 0.75rem; }
      .header-actions a { padding: 0.7rem 1rem; border-radius: 999px; border: 1px solid var(--border); background: #fff; color: var(--text); font-weight: 700; }
      .header-actions .primary { background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; border-color: transparent; }
      .container { max-width: 520px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      label { display: grid; gap: 0.4rem; font-weight: 600; margin-bottom: 0.8rem; }
      input { width: 100%; border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1rem; margin-top: 0.25rem; background: #fff; color: var(--text); }
      button { width: 100%; border: none; border-radius: 12px; padding: 0.95rem 1rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; font-weight: 700; cursor: pointer; }
      .status { display: none; margin-top: 1rem; padding: 0.85rem 1rem; border-radius: 12px; font-weight: 600; }
      .status.success { display: block; background: #ebf9f1; border: 1px solid rgba(22, 131, 75, 0.2); color: var(--success); }
      .status.error { display: block; background: #fff2f0; border: 1px solid rgba(217,45,32,0.2); color: var(--error); }
      .meta { margin-top: 0.85rem; color: var(--muted); font-size: 0.92rem; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <div class="header-actions">
        <a href="/login">Login</a>
        <a class="primary" href="/signup">Sign Up</a>
      </div>
    </header>

    <main class="container">
      <div class="card">
        <h1>Welcome back</h1>
        <p class="notice" style="margin-top:0;">Log in to access your secure application dashboard and continue where you left off.</p>
        <form id="loginForm">
          <label>Email ID
            <input name="email" type="email" placeholder="you@example.com" required />
          </label>
          <label>Mobile Number
            <input name="mobile" type="tel" maxlength="10" placeholder="10-digit mobile number" required />
          </label>
          <label>Password
            <input name="password" type="password" placeholder="Enter your password" required />
          </label>
          <button type="submit">Continue</button>
        </form>
        <div id="statusBox" class="status"></div>
      </div>
    </main>

    <script>
      const form = document.getElementById('loginForm');
      const statusBox = document.getElementById('statusBox');

      function setStatus(message, kind) {
        statusBox.className = `status ${kind}`;
        statusBox.textContent = message;
      }

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        try {
          const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Login failed.');

          setStatus('Login successful. Redirecting...', 'success');
          setTimeout(() => {
            window.location.href = '/verify-login';
          }, 900);
        } catch (error) {
          setStatus(error.message, 'error');
        }
      });
    </script>
  </body>
</html>
"""

OTP_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Verify Mobile | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --success: #16834B; --error: #D92D20; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: linear-gradient(180deg, #f6f9fd 0%, #eef5ff 100%); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228,234,242,0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 520px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      .notice { color: var(--muted); margin-bottom: 1rem; }
      label { display: grid; gap: 0.4rem; font-weight: 600; margin-bottom: 0.8rem; }
      input { width: 100%; border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1rem; margin-top: 0.25rem; background: #fff; color: var(--text); }
      .row { display: grid; gap: 1rem; }
      button { width: 100%; border: none; border-radius: 12px; padding: 0.95rem 1rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; font-weight: 700; cursor: pointer; }
      .meta { margin-top: 1rem; color: var(--muted); font-size: 0.9rem; }
      .status { display: none; margin-top: 1rem; padding: 0.85rem 1rem; border-radius: 12px; font-weight: 600; }
      .status.success { display: block; background: #ebf9f1; border: 1px solid rgba(22, 131, 75, 0.2); color: var(--success); }
      .status.error { display: block; background: #fff2f0; border: 1px solid rgba(217,45,32,0.2); color: var(--error); }
      .otp-box { display: none; margin-top: 1rem; }
      .otp-box.visible { display: block; }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Verify your mobile</h1>
        <p class="notice">Enter your mobile number to receive an OTP and continue to your pre-approved offer.</p>

        <div class="row">
          <label>Mobile number
            <input id="mobile" type="tel" maxlength="10" placeholder="Enter 10-digit mobile number" />
          </label>
          <button id="sendOtpBtn" type="button">Send OTP</button>
        </div>

        <div id="otpPanel" class="otp-box">
          <label>Enter OTP
            <input id="otp" type="text" maxlength="6" placeholder="Enter 6-digit OTP" />
          </label>
          <button id="verifyOtpBtn" type="button">Verify OTP</button>
          <button id="retryOtpBtn" type="button">Resend OTP</button>
        </div>

        <div id="statusBox" class="status"></div>
      </div>
    </main>

    <script type="text/javascript" onload="initSendOTP(configuration)" src="https://verify.msg91.com/otp-provider.js"></script>
    <script>
      const mobileInput = document.getElementById('mobile');
      const otpInput = document.getElementById('otp');
      const statusBox = document.getElementById('statusBox');
      const otpPanel = document.getElementById('otpPanel');
      const msg91WidgetId = {{ msg91_otp_widget_id | tojson }};
      const msg91WidgetTokenAuth = {{ msg91_otp_widget_token_auth | tojson }};
      const msg91WidgetEnabled = Boolean(msg91WidgetId && msg91WidgetTokenAuth);

      function setStatus(message, kind) {
        statusBox.className = `status ${kind}`;
        statusBox.textContent = message;
      }

      const urlParams = new URLSearchParams(window.location.search);
      const prefilledMobile = urlParams.get('mobile');
      if (prefilledMobile) {
        mobileInput.value = prefilledMobile;
      }

      function showWidgetError() {
        setStatus('OTP service is temporarily unavailable. Please try again later.', 'error');
      }

      const configuration = {
        widgetId: msg91WidgetId,
        tokenAuth: msg91WidgetTokenAuth,
        exposeMethods: true,
        success: async (accessToken) => {
          if (!msg91WidgetEnabled) {
            showWidgetError();
            return;
          }
          try {
            const response = await fetch('/api/verify-msg91-widget-token', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ mobile: mobileInput.value.trim(), accessToken })
            });
            const data = await response.json();
            if (response.status === 403 && data.blocked) {
              const params = new URLSearchParams({
                mobile: mobileInput.value.trim(),
                days: String(data.days_remaining || 30),
                reason: data.reason || 'Your application is temporarily paused.'
              });
              window.location.href = '/reapply-blocked?' + params.toString();
              return;
            }
            if (!response.ok) {
              showWidgetError();
              return;
            }
            window.location.href = data.next_url;
          } catch (error) {
            showWidgetError();
          }
        },
        failure: showWidgetError
      };

      document.getElementById('sendOtpBtn').addEventListener('click', () => {
        const mobile = mobileInput.value.trim();
        if (!/^\\d{10}$/.test(mobile)) {
          setStatus('Please enter a valid 10-digit mobile number.', 'error');
          return;
        }

        if (!msg91WidgetEnabled || typeof window.sendOtp !== 'function') {
          showWidgetError();
          return;
        }
        window.sendOtp(mobile, () => {
          otpPanel.classList.add('visible');
          setStatus(`OTP sent successfully to ${mobile}.`, 'success');
        }, showWidgetError);
      });

      document.getElementById('verifyOtpBtn').addEventListener('click', () => {
        const otp = otpInput.value.trim();

        if (!/^\\d{6}$/.test(otp)) {
          setStatus('Please enter the 6-digit OTP.', 'error');
          return;
        }

        if (!msg91WidgetEnabled || typeof window.verifyOtp !== 'function') {
          showWidgetError();
          return;
        }
        window.verifyOtp(otp, undefined, showWidgetError);
      });

      document.getElementById('retryOtpBtn').addEventListener('click', () => {
        if (!msg91WidgetEnabled || typeof window.retryOtp !== 'function') {
          showWidgetError();
          return;
        }
        window.retryOtp(null, () => {
          setStatus('OTP resent successfully.', 'success');
        }, showWidgetError);
      });
    </script>
  </body>
</html>
"""

PRE_APPROVAL_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Pre-Approved Offer | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --warning: #D97706;
        --gold: #f5c65d;
      }

      * { box-sizing: border-box; }
      html, body { margin: 0; min-height: 100%; }
      body {
        font-family: Inter, "Segoe UI", sans-serif;
        background: linear-gradient(180deg, #eff5ff 0%, #f9fbff 100%);
        color: var(--text);
        overflow-x: hidden;
      }
      a { text-decoration: none; color: inherit; }

      .confetti-layer {
        position: fixed;
        inset: 0;
        pointer-events: none;
        overflow: hidden;
        z-index: 0;
        filter: saturate(0.9);
      }
      .confetti {
        position: absolute;
        top: -18vh;
        width: 10px;
        height: 16px;
        border-radius: 3px;
        opacity: 0.9;
        box-shadow: 0 0 12px rgba(11, 61, 145, 0.08);
        animation: glide 6s ease-in forwards;
      }
      @keyframes glide {
        0% {
          transform: translate3d(0, 0, 0) rotate(0deg) scale(0.7);
          opacity: 0;
        }
        12% {
          opacity: 0.9;
        }
        35% {
          opacity: 0.8;
        }
        100% {
          transform: translate3d(var(--drift), 116vh, 0) rotate(500deg) scale(1);
          opacity: 0;
        }
      }

      .topbar {
        position: relative;
        z-index: 1;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: rgba(255,255,255,0.92);
        border-bottom: 1px solid rgba(228,234,242,0.8);
        backdrop-filter: blur(8px);
      }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark {
        display: inline-flex; align-items: center; justify-content: center;
        width: 2.1rem; height: 2.1rem; border-radius: 0.8rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: white;
      }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }

      .container {
        position: relative;
        z-index: 1;
        max-width: 980px;
        margin: 3rem auto;
        padding: 0 1.25rem 3rem;
      }
      .card {
        background: rgba(255,255,255,0.96);
        border: 1px solid var(--border);
        border-radius: 30px;
        padding: 2rem;
        box-shadow: 0 18px 40px rgba(11, 61, 145, 0.10);
      }
      .hero {
        display: grid;
        grid-template-columns: 1.15fr 0.85fr;
        gap: 1.5rem;
        align-items: center;
      }
      .celebration-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        background: linear-gradient(135deg, #eaf2ff, #d7e7ff);
        color: var(--primary);
        border: 1px solid rgba(11, 61, 145, 0.12);
        border-radius: 999px;
        padding: 0.55rem 0.9rem;
        font-size: 0.8rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .offer-header {
        margin-top: 1rem;
        font-size: clamp(1.35rem, 2vw, 2rem);
        font-weight: 900;
        letter-spacing: -0.03em;
        line-height: 1.1;
        white-space: normal;
      }
      .lead {
        margin: 0.8rem 0 0;
        font-size: 1.04rem;
        color: var(--muted);
        line-height: 1.7;
      }
      .offer-panel {
        position: relative;
        background: rgba(255, 255, 255, 0.26);
        border: 1px solid rgba(255, 255, 255, 0.5);
        border-radius: 24px;
        padding: 1.4rem;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 20px 45px rgba(27, 68, 153, 0.10);
        backdrop-filter: blur(10px);
        overflow: hidden;
      }
      .offer-panel::before {
        content: "";
        position: absolute;
        inset: -25% -15% auto auto;
        width: 180px;
        height: 180px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(78, 143, 255, 0.28), rgba(78, 143, 255, 0));
        filter: blur(8px);
      }
      .offer-panel::after {
        content: "";
        position: absolute;
        inset: 0 auto auto -12%;
        width: 140%;
        height: 100%;
        background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.38) 25%, transparent 50%);
        transform: translateX(-30%) skewX(-18deg);
        animation: shimmer 5.5s ease-in-out infinite;
      }
      @keyframes shimmer {
        0% { transform: translateX(-50%) skewX(-18deg); opacity: 0; }
        20% { opacity: 1; }
        60% { transform: translateX(28%) skewX(-18deg); opacity: 0.7; }
        100% { transform: translateX(54%) skewX(-18deg); opacity: 0; }
      }
      .offer-label {
        font-size: 0.76rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--muted);
        font-weight: 800;
        position: relative;
        z-index: 1;
      }
      .offer-amount {
        position: relative;
        z-index: 1;
        font-size: clamp(2.2rem, 5vw, 3.2rem);
        font-weight: 900;
        color: var(--primary);
        line-height: 1.1;
        margin: 0.6rem 0 0.15rem;
        text-shadow: 0 8px 24px rgba(29, 95, 233, 0.18);
      }
      .offer-note {
        position: relative;
        z-index: 1;
        color: var(--text);
        font-weight: 600;
      }

      .stats {
        margin-top: 1.5rem;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
      }
      .stat {
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 1rem;
      }
      .stat span {
        display: block;
        color: var(--muted);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 800;
      }
      .stat strong {
        display: block;
        margin-top: 0.45rem;
        font-size: 1.35rem;
        color: var(--text);
      }

      .calculator {
        margin-top: 2rem;
        border: 1px solid var(--border);
        border-radius: 24px;
        background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
        padding: 1.4rem;
      }
      .section-label {
        margin: 0 0 1rem;
        font-size: 1.1rem;
        font-weight: 800;
      }
      .tenure-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
      }
      .tenure-option {
        appearance: none;
        border: 1px solid var(--border);
        background: #fff;
        color: var(--text);
        font-weight: 700;
        border-radius: 12px;
        padding: 0.7rem 0.9rem;
        min-width: 82px;
        cursor: pointer;
        transition: 0.2s ease;
      }
      .tenure-option.active {
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: white;
        border-color: transparent;
        box-shadow: 0 8px 18px rgba(29, 95, 233, 0.22);
      }

      .estimate-box {
        margin-top: 1.3rem;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
      }
      .estimate {
        background: var(--primary-soft);
        border: 1px solid rgba(11, 61, 145, 0.12);
        border-radius: 18px;
        padding: 1rem;
      }
      .estimate small {
        display: block;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 800;
      }
      .estimate strong {
        display: block;
        margin-top: 0.4rem;
        font-size: 1.55rem;
        color: var(--primary);
      }

      .disclaimer {
        margin-top: 1.4rem;
        padding: 1rem;
        border-radius: 14px;
        background: #fff8ee;
        border: 1px solid rgba(217, 119, 6, 0.2);
        color: #7a4b00;
        line-height: 1.6;
      }
      .actions {
        margin-top: 1.5rem;
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
      }
      .cta {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0.95rem 1.4rem;
        background: linear-gradient(135deg, var(--primary), var(--secondary));
        color: #fff;
        border-radius: 12px;
        font-weight: 800;
        box-shadow: 0 10px 20px rgba(29, 95, 233, 0.18);
      }
      .ghost {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0.95rem 1.2rem;
        background: #fff;
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 12px;
        font-weight: 700;
      }

      @media (max-width: 760px) {
        .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; }
        .hero { grid-template-columns: 1fr; }
        .offer-header { white-space: normal; }
        .estimate-box { grid-template-columns: 1fr; }
        .stats { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="confetti-layer" id="confettiLayer" aria-hidden="true"></div>

    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <div class="hero">
          <div>
            <div class="celebration-badge">🎉 Your Offer is Ready</div>
            <div class="offer-header">Your pre-approved offer is ready.</div>
            <p class="lead">This is your single personalized offer for this demo profile. Review it and continue to the amount selection step.</p>
          </div>

          <div class="offer-panel">
            <div class="offer-label">One Personalized Offer</div>
            <div class="offer-amount">₹{{ offer_amount }}</div>
            <div class="offer-note">Demo-only offer based on your profile, age, and basic eligibility checks.</div>
          </div>
        </div>

        <div class="stats">
          <div class="stat">
            <span>Max Tenure</span>
            <strong>60 Months</strong>
          </div>
          <div class="stat">
            <span>Rate of Interest</span>
            <strong>11.5% p.a.</strong>
          </div>
        </div>

        <div class="calculator">
          <p class="section-label">Choose your preferred tenure</p>
          <div class="tenure-grid" id="tenureList">
            <button class="tenure-option" type="button" data-months="6">6 Months</button>
            <button class="tenure-option" type="button" data-months="12">12 Months</button>
            <button class="tenure-option" type="button" data-months="18">18 Months</button>
            <button class="tenure-option" type="button" data-months="24">24 Months</button>
            <button class="tenure-option" type="button" data-months="36">36 Months</button>
            <button class="tenure-option" type="button" data-months="48">48 Months</button>
            <button class="tenure-option active" type="button" data-months="60">60 Months</button>
          </div>

          <div class="estimate-box">
            <div class="estimate">
              <small>Estimated EMI</small>
              <strong id="emiValue">₹1,093</strong>
            </div>
            <div class="estimate">
              <small>Total Repayment</small>
              <strong id="totalValue">₹65,580</strong>
            </div>
          </div>
        </div>

        <div class="disclaimer">
          This is an indicative pre-approved offer and not a guaranteed final approval. Final approval remains subject to verification, documentation review, and underwriting checks.
        </div>

        <div class="actions">
          <a class="cta" href="/loan-amount-selection">Continue</a>
          <a class="ghost" href="/">Back to home</a>
        </div>
      </div>
    </main>

    <script>
      const principal = {{ offer_amount }};
      const annualRate = 11.5;
      const monthsOptions = Array.from(document.querySelectorAll('.tenure-option'));
      const emiValue = document.getElementById('emiValue');
      const totalValue = document.getElementById('totalValue');

      function formatCurrency(value) {
        return new Intl.NumberFormat('en-IN', {
          style: 'currency',
          currency: 'INR',
          maximumFractionDigits: 0
        }).format(value);
      }

      function calculateEMI(amount, months) {
        const monthlyRate = (annualRate / 12) / 100;
        if (monthlyRate === 0) return amount / months;
        const emi = (amount * monthlyRate * Math.pow(1 + monthlyRate, months)) / (Math.pow(1 + monthlyRate, months) - 1);
        return emi;
      }

      function updateCalculator(selectedMonths) {
        const emi = calculateEMI(principal, Number(selectedMonths));
        const total = emi * Number(selectedMonths);
        emiValue.textContent = formatCurrency(emi);
        totalValue.textContent = formatCurrency(total);
      }

      monthsOptions.forEach((option) => {
        option.addEventListener('click', () => {
          monthsOptions.forEach((btn) => btn.classList.remove('active'));
          option.classList.add('active');
          updateCalculator(option.dataset.months);
        });
      });

      updateCalculator(60);

      const confettiLayer = document.getElementById('confettiLayer');
      const colors = ['#0B3D91', '#1D5FE9', '#d7c9a7', '#dfeaff', '#b7d8ff', '#f5c65d'];
      const confettiCount = 34;

      for (let i = 0; i < confettiCount; i++) {
        const piece = document.createElement('span');
        piece.className = 'confetti';
        piece.style.left = `${Math.random() * 100}%`;
        piece.style.background = colors[Math.floor(Math.random() * colors.length)];
        piece.style.animationDelay = `${(Math.random() * 1.5).toFixed(2)}s`;
        piece.style.setProperty('--drift', `${(Math.random() * 140 - 70).toFixed(2)}px`);
        piece.style.transform = `scale(${(Math.random() * 0.9 + 0.55).toFixed(2)})`;
        piece.style.borderRadius = Math.random() > 0.6 ? '4px' : '50%';
        confettiLayer.appendChild(piece);
      }
    </script>
  </body>
</html>
"""

LOAN_AMOUNT_SELECTION_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Choose Loan Amount | CREDVEXA</title>
    <style>
      :root {
        --primary: #0B3D91;
        --secondary: #1D5FE9;
        --primary-soft: #EEF5FF;
        --bg: #F6F9FD;
        --card: #FFFFFF;
        --text: #14213D;
        --muted: #667085;
        --border: #E4EAF2;
        --success: #16834B;
        --warning: #D97706;
      }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: linear-gradient(180deg, #eff5ff 0%, #f9fbff 100%); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228,234,242,0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 980px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card {
        background: rgba(255,255,255,0.92);
        border: 1px solid rgba(228,234,242,0.9);
        border-radius: 30px;
        padding: 2rem;
        box-shadow: 0 18px 40px rgba(11, 61, 145, 0.10);
        backdrop-filter: blur(12px);
      }
      .eyebrow { display: inline-flex; align-items: center; border-radius: 999px; background: linear-gradient(135deg, #eaf2ff, #dfeaff); color: var(--primary); font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 800; padding: 0.5rem 0.8rem; }
      h1 { margin: 1rem 0 0.6rem; font-size: clamp(2rem, 4vw, 2.7rem); line-height: 1.1; }
      .subtitle { margin: 0; color: var(--muted); font-size: 1.03rem; line-height: 1.7; }
      .selection-panel {
        position: relative;
        margin-top: 2rem;
        background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(242,247,255,0.92));
        border: 1px solid rgba(143, 173, 255, 0.25);
        border-radius: 24px;
        padding: 1.4rem;
        backdrop-filter: blur(8px);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
        overflow: hidden;
      }
      .selection-panel::before {
        content: "";
        position: absolute;
        inset: -20% -10% auto auto;
        width: 220px;
        height: 220px;
        background: radial-gradient(circle, rgba(29,95,233,0.12), rgba(29,95,233,0));
        border-radius: 50%;
      }
      .range-head { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.9rem; }
      .range-head span { color: var(--muted); font-weight: 700; }
      .range-head strong { font-size: clamp(1.4rem, 2vw, 2rem); color: var(--primary); }
      input[type="range"] {
        position: relative; z-index: 1;
        width: 100%;
        height: 12px;
        background: linear-gradient(90deg, var(--primary) 0%, var(--secondary) 100%);
        border-radius: 999px;
        appearance: none;
        outline: none;
        box-shadow: inset 0 2px 4px rgba(11, 61, 145, 0.12);
      }
      input[type="range"]::-webkit-slider-runnable-track {
        height: 10px;
        border-radius: 999px;
        background: linear-gradient(90deg, rgba(11,61,145,0.18), rgba(29,95,233,0.12));
      }
      input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none;
        appearance: none;
        width: 26px;
        height: 26px;
        border-radius: 50%;
        background: linear-gradient(135deg, #ffffff, #edf4ff);
        border: 3px solid var(--primary);
        box-shadow: 0 4px 12px rgba(11, 61, 145, 0.25);
        margin-top: -8px;
        cursor: pointer;
      }
      input[type="range"]::-moz-range-track {
        height: 10px;
        border-radius: 999px;
        background: linear-gradient(90deg, rgba(11,61,145,0.18), rgba(29,95,233,0.12));
      }
      input[type="range"]::-moz-range-thumb {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        background: linear-gradient(135deg, #ffffff, #edf4ff);
        border: 3px solid var(--primary);
        box-shadow: 0 4px 12px rgba(11, 61, 145, 0.25);
        cursor: pointer;
        border: none;
      }
      .range-scale { position: relative; z-index: 1; display: flex; justify-content: space-between; margin-top: 0.9rem; color: var(--muted); font-size: 0.86rem; font-weight: 700; }
      .manual-wrap { position: relative; z-index: 1; margin-top: 1.2rem; }
      .field-label { display: block; margin-bottom: 0.55rem; font-weight: 700; }
      .input-wrap { position: relative; }
      .currency-prefix { position: absolute; left: 1rem; top: 50%; transform: translateY(-50%); font-weight: 700; color: var(--muted); }
      input[type="number"] { width: 100%; border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1rem 0.9rem 2.3rem; font-size: 1.1rem; font-weight: 700; color: var(--text); background: rgba(255,255,255,0.9); box-shadow: inset 0 1px 2px rgba(20,33,61,0.04); }
      .validation-message { min-height: 1.3rem; margin-top: 0.6rem; font-size: 0.92rem; font-weight: 600; color: #b42318; display: none; }
      .validation-message.show { display: block; }
      .summary-grid { margin-top: 1.6rem; display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 1rem; }
      .summary-card {
        background: linear-gradient(180deg, rgba(237,245,255,0.8), rgba(255,255,255,0.96));
        border: 1px solid rgba(143, 173, 255, 0.25);
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 8px 20px rgba(17, 49, 110, 0.05);
      }
      .summary-card small { display: block; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 800; }
      .summary-card strong { display: block; margin-top: 0.45rem; font-size: 1.3rem; color: var(--primary); }
      .calculator {
        margin-top: 2rem;
        border: 1px solid var(--border);
        border-radius: 24px;
        background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
        padding: 1.4rem;
      }
      .section-label { margin: 0 0 1rem; font-size: 1.1rem; font-weight: 800; }
      .tenure-grid { display: flex; flex-wrap: wrap; gap: 0.6rem; }
      .tenure-option { appearance: none; border: 1px solid var(--border); background: #fff; color: var(--text); font-weight: 700; border-radius: 12px; padding: 0.7rem 0.9rem; min-width: 82px; cursor: pointer; transition: 0.2s ease; }
      .tenure-option.active { background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; border-color: transparent; box-shadow: 0 8px 18px rgba(29, 95, 233, 0.22); }
      .info-note { margin-top: 1.1rem; color: var(--muted); line-height: 1.6; }
      .actions { margin-top: 1.5rem; display: flex; justify-content: flex-start; }
      .cta { display: inline-flex; align-items: center; justify-content: center; padding: 0.95rem 1.4rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; border-radius: 12px; font-weight: 800; box-shadow: 0 10px 20px rgba(29, 95, 233, 0.18); }
      @media (max-width: 760px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } .summary-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
      @media (max-width: 480px) { .summary-grid { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <div class="eyebrow">Pre-approved amount: ₹{{ pre_offer_amount }}</div>
        <h1>How Much Loan Do You Need?</h1>
        <p class="subtitle">You can choose any amount up to your pre-approved limit.</p>

        <div class="selection-panel">
          <div class="range-head">
            <span>Loan Amount</span>
            <strong id="sliderValue">₹30,000</strong>
          </div>

          <input id="loanRange" type="range" min="5000" max="{{ pre_offer_amount }}" step="1000" value="30000" />
          <div class="range-scale"><span>₹5,000</span><span>₹{{ pre_offer_amount }}</span></div>

          <div class="manual-wrap">
            <label class="field-label" for="manualAmount">Loan Amount</label>
            <div class="input-wrap">
              <span class="currency-prefix">₹</span>
              <input id="manualAmount" type="number" min="5000" max="{{ pre_offer_amount }}" step="1000" value="30000" />
            </div>
            <div id="validationMessage" class="validation-message" role="alert"></div>
          </div>

          <div class="quick-picks" style="position:relative;z-index:1;margin-top:1.25rem;display:flex;flex-wrap:wrap;gap:0.7rem;">
            <button class="quick-option" type="button" data-amount="5000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹5,000</button>
            <button class="quick-option" type="button" data-amount="10000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹10,000</button>
            <button class="quick-option" type="button" data-amount="15000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹15,000</button>
            <button class="quick-option" type="button" data-amount="20000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹20,000</button>
            <button class="quick-option" type="button" data-amount="25000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹25,000</button>
            <button class="quick-option" type="button" data-amount="50000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹50,000</button>
            <button class="quick-option" type="button" data-amount="75000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹75,000</button>
            <button class="quick-option" type="button" data-amount="100000" style="border:1px solid var(--border); border-radius: 10px; background:#fff; color:var(--text); font-weight:700; padding:0.7rem 0.9rem; cursor:pointer;">₹1,00,000</button>
          </div>
        </div>

        <div class="summary-grid">
          <div class="summary-card">
            <small>Selected Loan Amount</small>
            <strong id="selectedAmount">₹30,000</strong>
          </div>
          <div class="summary-card">
            <small>Tenure</small>
            <strong id="selectedTenure">12 Months</strong>
          </div>
          <div class="summary-card">
            <small>Estimated EMI</small>
            <strong id="emiValue">₹2,627 / month</strong>
          </div>
          <div class="summary-card">
            <small>Total Repayment</small>
            <strong id="totalValue">₹31,522</strong>
          </div>
        </div>

        <div class="calculator">
          <p class="section-label">Choose Your Tenure</p>
          <div class="tenure-grid" id="tenureList">
            <button class="tenure-option" type="button" data-months="6">6 Months</button>
            <button class="tenure-option active" type="button" data-months="12">12 Months</button>
            <button class="tenure-option" type="button" data-months="18">18 Months</button>
            <button class="tenure-option" type="button" data-months="24">24 Months</button>
            <button class="tenure-option" type="button" data-months="30">30 Months</button>
            <button class="tenure-option" type="button" data-months="36">36 Months</button>
            <button class="tenure-option" type="button" data-months="48">48 Months</button>
            <button class="tenure-option" type="button" data-months="60">60 Months</button>
          </div>
        </div>

        <p class="info-note">EMI and repayment figures shown are estimates and may be subject to final eligibility, terms and applicable charges.</p>

        <div class="actions">
          <a class="cta" href="/document-verification">Continue</a>
        </div>
      </div>
    </main>

    <script>
      const MAX_LIMIT = Number('{{ pre_offer_amount }}');
      const MIN_LIMIT = 5000;
      const annualRate = 11.5;
      const slider = document.getElementById('loanRange');
      const manualAmount = document.getElementById('manualAmount');
      const sliderValue = document.getElementById('sliderValue');
      const selectedAmount = document.getElementById('selectedAmount');
      const selectedTenure = document.getElementById('selectedTenure');
      const emiValue = document.getElementById('emiValue');
      const totalValue = document.getElementById('totalValue');
      const validationMessage = document.getElementById('validationMessage');
      const tenureButtons = Array.from(document.querySelectorAll('.tenure-option'));
      const quickButtons = Array.from(document.querySelectorAll('.quick-option'));
      let currentTenure = 12;

      function formatCurrency(value) {
        return new Intl.NumberFormat('en-IN', {
          style: 'currency',
          currency: 'INR',
          maximumFractionDigits: 0
        }).format(value);
      }

      function calculateEMI(amount, months) {
        const monthlyRate = (annualRate / 12) / 100;
        if (monthlyRate === 0) return amount / months;
        return (amount * monthlyRate * Math.pow(1 + monthlyRate, months)) / (Math.pow(1 + monthlyRate, months) - 1);
      }

      function clearValidation() {
        validationMessage.textContent = '';
        validationMessage.classList.remove('show');
      }

      function showValidation(message) {
        validationMessage.textContent = message;
        validationMessage.classList.add('show');
      }

      function updateSummary() {
        const amount = Number(slider.value);
        const emi = calculateEMI(amount, currentTenure);
        const total = emi * currentTenure;
        sliderValue.textContent = formatCurrency(amount);
        selectedAmount.textContent = formatCurrency(amount);
        selectedTenure.textContent = `${currentTenure} Months`;
        emiValue.textContent = `${formatCurrency(emi)} / month`;
        totalValue.textContent = formatCurrency(total);
      }

      function syncAmount(value) {
        let nextValue = Number(value);
        if (Number.isNaN(nextValue)) nextValue = MIN_LIMIT;
        if (nextValue < MIN_LIMIT) nextValue = MIN_LIMIT;
        if (nextValue > MAX_LIMIT) nextValue = MAX_LIMIT;
        slider.value = String(nextValue);
        manualAmount.value = String(nextValue);
        updateSummary();
      }

      slider.addEventListener('input', () => {
        clearValidation();
        syncAmount(slider.value);
      });

      manualAmount.addEventListener('input', () => {
        const raw = manualAmount.value.trim();
        if (raw === '') {
          clearValidation();
          return;
        }

        const enteredValue = Number(raw);
        if (enteredValue > MAX_LIMIT) {
          showValidation(`Please enter an amount within your pre-approved limit of ${formatCurrency(MAX_LIMIT)}.`);
          return;
        }

        if (enteredValue < MIN_LIMIT) {
          showValidation(`Please enter an amount of at least ${formatCurrency(MIN_LIMIT)}.`);
          return;
        }

        clearValidation();
        syncAmount(enteredValue);
      });

      tenureButtons.forEach((button) => {
        button.addEventListener('click', () => {
          tenureButtons.forEach((btn) => btn.classList.remove('active'));
          button.classList.add('active');
          currentTenure = Number(button.dataset.months);
          updateSummary();
        });
      });

      quickButtons.forEach((button) => {
        button.addEventListener('click', () => {
          const selection = Number(button.dataset.amount);
          if (selection > MAX_LIMIT) {
            showValidation(`Please enter an amount within your pre-approved limit of ${formatCurrency(MAX_LIMIT)}.`);
            return;
          }
          clearValidation();
          syncAmount(selection);
        });
      });

      updateSummary();
    </script>
  </body>
</html>
"""

DOCUMENT_VERIFICATION_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Verification & Processing | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --success: #16834B; --error: #D92D20; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
      a { text-decoration: none; color: inherit; }
      .topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: rgba(255,255,255,0.92); border-bottom: 1px solid rgba(228,234,242,0.8); }
      .brand { display: inline-flex; align-items: center; gap: 0.7rem; font-size: 1.45rem; font-weight: 800; color: var(--primary); }
      .brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 2.1rem; height: 2.1rem; border-radius: 0.8rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }
      nav { display: flex; gap: 1rem; flex-wrap: wrap; }
      nav a { color: var(--text); font-weight: 600; padding: 0.4rem 0.65rem; border-radius: 999px; }
      nav a:hover { background: var(--primary-soft); color: var(--primary); }
      .container { max-width: 760px; margin: 3rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      h1 { margin-top: 0; }
      .lead { color: var(--muted); line-height: 1.7; }
      .fee-box { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 18px; padding: 1rem 1.1rem; margin: 1.2rem 0; }
      .fee-box strong { font-size: 2rem; }
      .disclosure { background: #fffaf2; border: 1px solid rgba(217,119,6,0.2); color: #7a4b00; border-radius: 14px; padding: 1rem; line-height: 1.6; margin: 1rem 0; }
      .document-box { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 18px; padding: 1.15rem; margin: 1.2rem 0; }
      .document-box h3 { margin: 0 0 0.35rem; }
      .document-box p { margin: 0 0 1rem; color: var(--muted); line-height: 1.6; }
      .upload-label { display: grid; gap: 0.45rem; font-weight: 600; margin-bottom: 0.9rem; }
      .upload-label input { width: 100%; padding: 0.8rem 0.9rem; border: 1px solid var(--border); border-radius: 10px; background: #fff; }
      .check-row { display: flex; align-items: center; gap: 0.7rem; font-weight: 600; margin: 0.25rem 0 1rem; }
      .check-row input { width: 1.1rem; height: 1.1rem; }
      .password-box { margin-top: 0.75rem; }
      .password-box.hidden { display: none; }
      .password-box label { display: block; margin-bottom: 0.5rem; font-weight: 700; }
      .password-row { display: flex; gap: 0.75rem; }
      .password-row input { flex: 1; padding: 0.9rem 1rem; border-radius: 12px; border: 1px solid var(--border); }
      .secondary-btn { width: auto; min-width: 150px; border: none; border-radius: 12px; padding: 0.9rem 1rem; background: #eef5ff; color: var(--primary); font-weight: 700; cursor: pointer; }
      .methods { display: grid; gap: 0.9rem; margin-top: 1.2rem; }
      .method { display: flex; align-items: center; justify-content: space-between; gap: 1rem; width: 100%; padding: 1rem; border-radius: 12px; border: 1px solid var(--border); background: #fff; font-weight: 700; cursor: pointer; }
      .method.selected { border-color: var(--primary); background: var(--primary-soft); }
      button { width: 100%; margin-top: 1.5rem; border: none; border-radius: 12px; padding: 0.95rem 1rem; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; font-weight: 700; cursor: pointer; }
      .status { margin-top: 1rem; display: none; padding: 0.85rem 1rem; border-radius: 12px; font-weight: 600; }
      .status.success { display: block; background: #ebf9f1; border: 1px solid rgba(22, 131, 75, 0.2); color: var(--success); }
      .status.error { display: block; background: #fff2f0; border: 1px solid rgba(217,45,32,0.2); color: var(--error); }
      @media (max-width: 700px) { .topbar { flex-direction: column; align-items: flex-start; gap: 0.8rem; } }
    </style>
  </head>
  <body>
    <header class="topbar">
      <div class="brand"><span class="brand-mark">C</span> CREDVEXA</div>
      <nav>
        <a href="/">Home</a>
        <a href="/apply">Apply</a>
        <a href="/track">Track</a>
        <a href="/dashboard">Dashboard</a>
      </nav>
    </header>

    <main class="container">
      <div class="card">
        <h1>Complete Your Verification</h1>
        <p class="lead">Your application is ready for the next verification stage. This demo includes a mock verification or processing charge that helps simulate the final step of the flow.</p>

        <div class="fee-box">
          <div>Verification / Processing Fee</div>
          <strong>₹199</strong>
        </div>

        <div class="disclosure">
          Applicable verification or processing charges, if any, will be disclosed according to the applicable terms and conditions. This demo uses a mock payment amount of ₹199 and does not represent a real financial commitment or guarantee of approval.
        </div>

        <div class="document-box">
          <h3>Bank account statement (last 3 months) required</h3>
          <p>Please upload your latest 3-month bank account statement for income and repayment assessment.</p>

          <label class="upload-label" for="bankStatementUpload">
            <span>Upload statement</span>
            <input id="bankStatementUpload" type="file" accept=".pdf,.jpg,.jpeg,.png" />
          </label>

          <label class="check-row" for="statementPasswordProtected">
            <input id="statementPasswordProtected" type="checkbox" />
            <span>This bank statement is password protected</span>
          </label>

          <div id="passwordBox" class="password-box hidden">
            <label for="statementPassword">Statement password</label>
            <div class="password-row">
              <input id="statementPassword" type="password" placeholder="Enter statement password" />
              <button type="button" class="secondary-btn" id="addPasswordBtn">Add password</button>
            </div>
          </div>
        </div>

        <div class="methods">
          <button class="method selected" type="button">UPI / Wallet</button>
          <button class="method" type="button">Credit / Debit Card</button>
          <button class="method" type="button">Net Banking</button>
        </div>

        <button id="payBtn" type="button">Pay ₹199</button>
        <div id="statusBox" class="status"></div>
      </div>
    </main>

    <script>
      const payBtn = document.getElementById('payBtn');
      const statusBox = document.getElementById('statusBox');
      const methodButtons = Array.from(document.querySelectorAll('.method'));
      const passwordProtectedToggle = document.getElementById('statementPasswordProtected');
      const passwordBox = document.getElementById('passwordBox');
      const addPasswordBtn = document.getElementById('addPasswordBtn');

      function setStatus(message, kind) {
        statusBox.className = `status ${kind}`;
        statusBox.textContent = message;
      }

      passwordProtectedToggle.addEventListener('change', () => {
        passwordBox.classList.toggle('hidden', !passwordProtectedToggle.checked);
      });

      addPasswordBtn.addEventListener('click', () => {
        const password = document.getElementById('statementPassword').value.trim();
        if (!passwordProtectedToggle.checked) {
          setStatus('Please confirm that the statement is password protected before adding a password.', 'error');
          return;
        }
        if (!password) {
          setStatus('Please enter the bank statement password.', 'error');
          return;
        }
        setStatus('Statement password saved for review.', 'success');
      });

      methodButtons.forEach((button) => {
        button.addEventListener('click', () => {
          methodButtons.forEach((btn) => btn.classList.remove('selected'));
          button.classList.add('selected');
        });
      });

      payBtn.addEventListener('click', async () => {
        try {
          const response = await fetch('/api/pay-verification-fee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount: 199 })
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Payment failed.');

          setStatus('Payment successful. Your payment has been recorded in this demo. Application status: Verification in Progress.', 'success');
          setTimeout(() => {
            window.location.href = data.next_url || '/application-received';
          }, 1200);
        } catch (error) {
          setStatus(error.message, 'error');
        }
      });
    </script>
  </body>
</html>
"""

APPLICATION_RECEIVED_HTML = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Application Received | CREDVEXA</title>
    <style>
      :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --success: #16834B; }
      * { box-sizing: border-box; }
      body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: linear-gradient(180deg, #f6f9fd 0%, #eef5ff 100%); color: var(--text); }
      .container { max-width: 760px; margin: 4rem auto; padding: 0 1.25rem 3rem; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
      .icon { width: 4rem; height: 4rem; border-radius: 50%; display: grid; place-items: center; background: #ebf9f1; color: var(--success); font-size: 2rem; margin-bottom: 1rem; }
      h1 { margin: 0 0 0.75rem; }
      p { color: var(--muted); line-height: 1.7; }
      .note { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 16px; padding: 1rem; margin-top: 1rem; font-weight: 600; }
      a { color: var(--primary); text-decoration: none; font-weight: 700; }
    </style>
  </head>
  <body>
    <main class="container">
      <div class="card">
        <div class="icon">✓</div>
        <h1>Application received</h1>
        <p>We have received your submission and your application is now under review.</p>
        <p>Our review team is checking the details and the verification step you completed. Please wait a few minutes and keep your phone available for updates or notifications.</p>

        <div class="note">
          You will receive a notification once the loan request is reviewed and a final decision is communicated.
        </div>

        <p style="margin-top:1.25rem;"><a href="/">Return to home</a></p>
      </div>
    </main>
  </body>
</html>
"""


@app.route("/")
def home_page():
    return render_template_string(INDEX_HTML)


@app.route("/about")
def about_page():
    return render_template_string(ABOUT_HTML)


@app.route("/contact")
def contact_page():
    return render_template_string(CONTACT_HTML)


@app.route("/privacy")
def privacy_page():
    return render_template_string(PRIVACY_HTML)


@app.route("/terms")
def terms_page():
    return render_template_string(TERMS_HTML)


@app.route("/faq")
def faq_page():
    return render_template_string(FAQ_HTML)


@app.route("/blog")
def blog_page():
    return render_template_string(BLOG_HTML)


@app.route("/calculator")
def calculator_page():
    return render_template_string(CALCULATOR_HTML)


@app.route("/signup")
def signup_page():
    return render_template_string(SIGNUP_HTML)


@app.route("/login")
def login_page():
    return render_template_string(LOGIN_HTML)


@app.route("/logout")
def logout_page():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/verify-login")
def otp_login_page():
    return render_template_string(
        OTP_LOGIN_HTML,
        msg91_otp_widget_id=MSG91_OTP_WIDGET_ID,
        msg91_otp_widget_token_auth=MSG91_OTP_WIDGET_TOKEN_AUTH,
    )


@app.route("/pre-approved-loan")
def pre_approved_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    offer_amount = int(session.get("pre_offer_amount") or 50000)
    max_tenure_months = 60
    return render_template_string(PRE_APPROVAL_HTML, offer_amount=offer_amount, max_tenure_months=max_tenure_months)


@app.route("/loan-amount-selection")
def loan_amount_selection_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    pre_offer_amount = int(session.get("pre_offer_amount") or 50000)
    return render_template_string(LOAN_AMOUNT_SELECTION_HTML, pre_offer_amount=pre_offer_amount)


@app.route("/document-verification")
def document_verification_page():
    return render_template_string(DOCUMENT_VERIFICATION_HTML)


@app.route("/reapply-blocked")
def reapply_blocked_page():
    mobile = request.args.get("mobile", "")
    days_remaining = max(1, int(request.args.get("days", "30")))
    reason = request.args.get("reason", generate_rejection_reason())
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>Application Paused | CREDVEXA</title>
            <style>
              :root { --primary: #0B3D91; --secondary: #1D5FE9; --primary-soft: #EEF5FF; --bg: #F6F9FD; --card: #FFFFFF; --text: #14213D; --muted: #667085; --border: #E4EAF2; --error: #D92D20; }
              * { box-sizing: border-box; }
              body { margin: 0; font-family: Inter, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
              .container { max-width: 760px; margin: 4rem auto; padding: 0 1.25rem 3rem; }
              .card { background: var(--card); border: 1px solid var(--border); border-radius: 28px; padding: 2rem; box-shadow: 0 12px 32px rgba(11, 61, 145, 0.08); }
              h1 { margin-top: 0; }
              p { color: var(--muted); line-height: 1.7; }
              .warning { background: #fff4f1; border: 1px solid rgba(217,45,32,0.2); border-radius: 16px; color: var(--error); padding: 1rem 1.1rem; font-weight: 700; margin: 1rem 0; }
              .reason { background: var(--primary-soft); border: 1px solid var(--border); border-radius: 16px; padding: 1rem; }
              a { color: var(--primary); font-weight: 700; text-decoration: none; }
            </style>
          </head>
          <body>
            <main class="container">
              <div class="card">
                <h1>Application temporarily paused</h1>
                <p>Hi {{ mobile or 'candidate' }}, your previous application was rejected and the system has temporarily paused new submissions from this profile.</p>
                <div class="warning">You can apply again after {{ days_remaining }} days.</div>
                <div class="reason"><strong>Reason:</strong> {{ reason }}</div>
                <p>This lock is in place to protect the review process after a rejected application and a payment-related review concern.</p>
                <p><a href="/verify-login">Try a different mobile number</a></p>
              </div>
            </main>
          </body>
        </html>
        """,
        mobile=mobile,
        days_remaining=days_remaining,
        reason=reason,
    )


@app.route("/application-received")
def application_received_page():
    return render_template_string(APPLICATION_RECEIVED_HTML)


@app.route("/api/signup", methods=["POST"])
def api_signup():
    payload = request.get_json(silent=True) or {}
    try:
        user = create_user_account(payload)
        return jsonify({"message": "Account created successfully.", "user": {"full_name": user["full_name"], "email": user["email"], "mobile": user["mobile"]}}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/login", methods=["POST"])
def api_login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    mobile = str(payload.get("mobile", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not (email or mobile):
        return jsonify({"error": "Please enter your email or mobile number."}), 400
    if not password:
        return jsonify({"error": "Please enter your password."}), 400

    user = authenticate_user(email or mobile, password)
    if user is None:
        return jsonify({"error": "Invalid email/mobile or password."}), 401

    session["logged_in"] = True
    session["user_email"] = user["email"]
    session["user_mobile"] = user["mobile"]
    session["user_name"] = user["full_name"]
    saved_approved_amount = get_saved_approved_amount(user["mobile"])
    if saved_approved_amount is not None:
      session["pre_offer_amount"] = saved_approved_amount
    return jsonify({"message": "Login successful.", "user": {"name": user["full_name"], "mobile": user["mobile"]}}), 200


@app.route("/api/verify-msg91-widget-token", methods=["POST"])
def api_verify_msg91_widget_token():
    payload = request.get_json(silent=True) or {}
    mobile = str(payload.get("mobile", "")).strip()
    access_token = str(payload.get("accessToken", "")).strip()
    if not validate_mobile(mobile) or not access_token:
        return jsonify({"error": "OTP verification failed. Please try again."}), 400

    try:
      verified_token = verify_msg91_widget_access_token(access_token)
    except ValueError:
        return jsonify({"error": "OTP verification failed. Please try again."}), 401
    except RuntimeError:
        return jsonify({"error": "OTP verification is temporarily unavailable. Please try again later."}), 503

    verified_mobile = str((verified_token.get("data") or {}).get("mobile", "")).strip()
    if normalize_msg91_mobile(verified_mobile) != normalize_msg91_mobile(mobile):
      return jsonify({"error": "OTP verification failed. Please try again."}), 401

    block = get_reapply_block(mobile=mobile)
    if block["blocked"]:
      return jsonify({
        "blocked": True,
        "message": "Your application is temporarily paused.",
        "days_remaining": block["days_remaining"],
        "reason": block["reason"],
      }), 403

    session["logged_in"] = True
    session["candidate_mobile"] = mobile
    session["otp_verified"] = True
    if "user_name" not in session:
        session["user_name"] = "Customer"
    offer = get_preapproved_offer_for_candidate(mobile=mobile)
    session["pre_offer_amount"] = get_saved_approved_amount(mobile) or offer["offer_amount"]
    return jsonify({"message": "OTP verified successfully.", "next_url": "/apply"})


@app.route("/api/pay-verification-fee", methods=["POST"])
def api_pay_verification_fee():
    payload = request.get_json(silent=True) or {}
    amount = payload.get("amount")
    if amount != 199:
        return jsonify({"error": "Verification fee must be ₹199."}), 400
    return jsonify({
        "message": "Verification fee received.",
        "amount": 199,
        "status": "PAID",
        "next_url": "/application-received",
    })


@app.route("/apply")
def apply_page():
    if not session.get("otp_verified"):
        return redirect(url_for("otp_login_page"))
    return render_template_string(APPLY_HTML)


@app.route("/track")
def track_page():
    return render_template_string(TRACK_HTML)


@app.route("/dashboard")
def dashboard_page():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/applications", methods=["POST"])
def api_create_application():
    try:
        payload = request.get_json(silent=True) or {}
        app_record = create_application(payload)
        session["application_id"] = app_record["application_id"]
        generated_offer = generate_age_based_offer(app_record.get("age") or 25)
        save_approved_amount(app_record["application_id"], generated_offer)
        session["pre_offer_amount"] = generated_offer
        session["application_submitted"] = True
        return jsonify({
            "message": "Application submitted successfully.",
            "application_id": app_record["application_id"],
            "status": app_record["status"],
            "emi": app_record["emi"],
            "note": app_record["note"],
            "offer_amount": generated_offer,
            "next_url": "/pre-approved-loan",
        }), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/track/<application_id>/<mobile>", methods=["GET"])
def api_track_application(application_id, mobile):
    record = find_application(application_id=application_id, mobile=mobile)
    if not record:
        return jsonify({"error": "Application not found."}), 404
    return jsonify(record)


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    records = load_applications()
    under_review = sum(1 for item in records if str(item.get("status", "")).upper() == "UNDER_REVIEW")
    approved = sum(1 for item in records if str(item.get("status", "")).upper() == "APPROVED")
    return jsonify({
        "total": len(records),
        "under_review": under_review,
        "approved": approved,
        "applications": records,
    })


@app.route("/api/admin/applications", methods=["GET"])
def admin_list_applications():
    return jsonify(load_applications())


@app.route("/api/admin/application/<application_id>/status", methods=["PATCH"])
def admin_update_application(application_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status", "UNDER_REVIEW")
    note = payload.get("note", "Status updated.")
    try:
        updated = update_application_status(application_id, status, note)
        return jsonify({"message": "Status updated.", "application": updated})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


if __name__ == "__main__":
  print(f"{APP_NAME} is running on http://{settings.host}:{settings.port}")
  app.run(debug=settings.debug, host=settings.host, port=settings.port)
