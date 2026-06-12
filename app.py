from __future__ import annotations

import sqlite3
import socket
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "healthcare.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "ai-healthcare-local-secret"
app.config["UPLOAD_FOLDER"] = BASE_DIR / "uploads"


STATS = {
    "patients": 1284,
    "doctors": 42,
    "beds_available": 64,
    "appointments_today": 86,
}

DOCTORS = [
    {"name": "Dr. Ananya Rao", "department": "Cardiology", "status": "Available", "phone": "+91 98765 21001", "room": "C-204"},
    {"name": "Dr. Vikram Sen", "department": "Nephrology", "status": "In Surgery", "phone": "+91 98765 21002", "room": "N-118"},
    {"name": "Dr. Meera Iyer", "department": "Oncology", "status": "Available", "phone": "+91 98765 21003", "room": "O-310"},
]

APPOINTMENTS = [
    {"patient": "Rahul Kumar", "doctor": "Dr. Ananya Rao", "time": "10:30 AM", "status": "Confirmed"},
    {"patient": "Sneha Reddy", "doctor": "Dr. Meera Iyer", "time": "12:00 PM", "status": "Pending"},
    {"patient": "Arjun Das", "doctor": "Dr. Vikram Sen", "time": "03:15 PM", "status": "Confirmed"},
]

PATIENTS = [
    {"name": "Rahul Kumar", "age": 48, "condition": "Hypertension", "risk": "Medium", "last_visit": "12 Jun 2026"},
    {"name": "Sneha Reddy", "age": 36, "condition": "Diabetes Follow-up", "risk": "Low", "last_visit": "10 Jun 2026"},
    {"name": "Arjun Das", "age": 61, "condition": "Kidney Monitoring", "risk": "High", "last_visit": "09 Jun 2026"},
    {"name": "Priya Sharma", "age": 29, "condition": "General Checkup", "risk": "Low", "last_visit": "08 Jun 2026"},
]

REPORTS = [
    {
        "id": "patient-summary",
        "title": "Patient Summary Report",
        "type": "TXT",
        "description": "Overall patient count, doctor availability, beds, and daily appointment summary.",
    },
    {
        "id": "lab-report",
        "title": "Sample Lab Report",
        "type": "TXT",
        "description": "Demo blood sugar, blood pressure, kidney marker, and follow-up notes.",
    },
    {
        "id": "appointments",
        "title": "Appointments Export",
        "type": "CSV",
        "description": "Download today's appointment queue in spreadsheet format.",
    },
]


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'patient',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                doctor_name TEXT NOT NULL,
                department TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing == 0:
            conn.executemany(
                """
                INSERT INTO users (name, email, password, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("Admin User", "admin@healthcare.local", "admin123", "admin", datetime.now().isoformat()),
                    ("Doctor Demo", "doctor@healthcare.local", "doctor123", "doctor", datetime.now().isoformat()),
                    ("Patient Demo", "patient@healthcare.local", "patient123", "patient", datetime.now().isoformat()),
                ],
            )


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


@app.context_processor
def inject_user() -> dict:
    return {"current_user": current_user()}


def disease_risk_score(form: dict) -> tuple[str, int, list[str]]:
    age = int(form.get("age") or 0)
    glucose = int(form.get("glucose") or 0)
    bp = int(form.get("bp") or 0)
    symptoms = request.form.getlist("symptoms")

    score = 10
    reasons: list[str] = []
    if age >= 55:
        score += 18
        reasons.append("Age needs closer monitoring")
    if glucose >= 140:
        score += 26
        reasons.append("Glucose is above the safe range")
    if bp >= 140:
        score += 22
        reasons.append("Blood pressure is high")
    if len(symptoms) >= 2:
        score += 20
        reasons.append("Multiple symptoms selected")

    score = min(score, 96)
    if score >= 65:
        return "High Risk", score, reasons
    if score >= 35:
        return "Medium Risk", score, reasons
    return "Low Risk", score, reasons or ["Inputs are within a lower-risk range"]


def chatbot_reply(message: str) -> str:
    text = message.lower()
    if any(word in text for word in ["fever", "temperature", "cold"]):
        return "Drink fluids, rest, and monitor your temperature. If fever is high or lasts more than 2 days, consult a doctor."
    if any(word in text for word in ["chest", "heart", "pain"]):
        return "Chest pain can be serious. Please contact emergency care immediately if pain is severe, spreading, or with breathlessness."
    if any(word in text for word in ["sugar", "diabetes", "glucose"]):
        return "Track fasting sugar, avoid high-sugar food, and book a consultation if readings stay high."
    if any(word in text for word in ["appointment", "doctor", "booking"]):
        return "You can book an appointment from the Patient Dashboard. Choose department, doctor, date, and reason."
    return "I can help with symptoms, appointments, reports, and basic hospital guidance. For emergencies, call local emergency services."


def report_file(report_id: str) -> tuple[str, str, bytes]:
    today = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    if report_id == "patient-summary":
        content = f"""AI Healthcare System - Patient Summary Report
Generated: {today}

Total Patients: {STATS["patients"]}
Doctors Available: {STATS["doctors"]}
Beds Available: {STATS["beds_available"]}
Appointments Today: {STATS["appointments_today"]}

Doctor Status
-------------
"""
        for doctor in DOCTORS:
            content += f'{doctor["name"]} | {doctor["department"]} | {doctor["status"]}\n'
        return "patient_summary_report.txt", "text/plain", content.encode("utf-8")

    if report_id == "lab-report":
        content = f"""AI Healthcare System - Sample Lab Report
Generated: {today}

Patient Name: Patient Demo
Blood Sugar: 118 mg/dL
Blood Pressure: 126/82 mmHg
Creatinine: 0.9 mg/dL
Hemoglobin: 13.8 g/dL

Doctor Note:
Vitals are stable in this demo report. Continue regular monitoring and follow up if symptoms increase.
"""
        return "sample_lab_report.txt", "text/plain", content.encode("utf-8")

    if report_id == "appointments":
        rows = ["patient,doctor,time,status"]
        rows.extend(f'{item["patient"]},{item["doctor"]},{item["time"]},{item["status"]}' for item in APPOINTMENTS)
        return "appointments_report.csv", "text/csv", "\n".join(rows).encode("utf-8")

    abort(404)


def find_free_port(start: int = 5000) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free local port found between 5000 and 5049.")


@app.route("/")
def index():
    return render_template("index.html", stats=STATS, doctors=DOCTORS, appointments=APPOINTMENTS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        selected_role = request.form["role"]
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                conn.execute("UPDATE users SET password = ?, role = ? WHERE id = ?", (password, selected_role, user["id"]))
                user_id = user["id"]
            else:
                name = email.split("@")[0].replace(".", " ").replace("_", " ").title() or selected_role.title()
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, email, password, selected_role, datetime.now().isoformat()),
                )
                user_id = cursor.lastrowid
        session["user_id"] = user_id
        flash("Login successful.", "success")
        return redirect(url_for(f"{selected_role}_dashboard"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = (
            request.form["name"].strip(),
            request.form["email"].strip().lower(),
            request.form["password"],
            request.form.get("role", "patient"),
            datetime.now().isoformat(),
        )
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (name, email, password, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    data,
                )
            flash("Account created. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already exists.", "error")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("index"))


@app.route("/patient")
def patient_dashboard():
    tomorrow = datetime.now() + timedelta(days=1)
    return render_template("patient/patient_dashboard.html", appointments=APPOINTMENTS, doctors=DOCTORS, tomorrow=tomorrow)


@app.route("/doctor")
def doctor_dashboard():
    return render_template("doctor/doctor_dashboard.html", appointments=APPOINTMENTS, patients=PATIENTS)


@app.route("/admin")
def admin_dashboard():
    return render_template("admin/admin_dashboard.html", stats=STATS, doctors=DOCTORS)


@app.route("/appointments", methods=["GET", "POST"])
def appointments():
    if request.method == "POST":
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO appointments
                (patient_name, doctor_name, department, appointment_date, appointment_time, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.form["patient_name"],
                    request.form["doctor_name"],
                    request.form["department"],
                    request.form["appointment_date"],
                    request.form["appointment_time"],
                    request.form["reason"],
                    datetime.now().isoformat(),
                ),
            )
        flash("Appointment booked successfully.", "success")
        return redirect(url_for("appointments"))

    with get_db() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY id DESC").fetchall()
    return render_template("patient/appointments.html", appointments=rows, doctors=DOCTORS)


@app.route("/prediction", methods=["GET", "POST"])
def prediction():
    result = None
    if request.method == "POST":
        label, score, reasons = disease_risk_score(request.form)
        result = {"label": label, "score": score, "reasons": reasons}
    return render_template("patient/reports.html", result=result, reports=REPORTS)


@app.route("/reports")
def reports():
    return render_template("patient/reports.html", result=None, reports=REPORTS)


@app.route("/reports/download/<report_id>")
def download_report(report_id: str):
    filename, mimetype, content = report_file(report_id)
    return send_file(
        BytesIO(content),
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
    )


@app.route("/chatbot", methods=["GET", "POST"])
def chatbot():
    answer = None
    question = ""
    if request.method == "POST":
        question = request.form.get("message", "")
        answer = chatbot_reply(question)
    return render_template("chatbot.html", question=question, answer=answer)


@app.route("/analytics")
def analytics():
    bed_data = {"ICU": 12, "General": 38, "Emergency": 14}
    return render_template("admin/analytics.html", stats=STATS, bed_data=bed_data)


if __name__ == "__main__":
    init_db()
    port = find_free_port()
    print(f"AI Healthcare System running at http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
