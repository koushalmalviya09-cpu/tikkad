import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import date, datetime
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hotel.db")

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=43200,
)

# Development code: 4821. Set STAFF_ACCESS_CODE and restart before going live.
STAFF_CODE = os.environ.get("STAFF_ACCESS_CODE", "ILOVEFOODFROMTIKKAD")
STAFF_CODE_HASH = generate_password_hash(STAFF_CODE)

login_attempts = defaultdict(deque)
booking_attempts = defaultdict(deque)


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            guests INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            ip_address TEXT,
            created_at TEXT NOT NULL
        );
        """)


init_db()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    return response


def recent_attempts(store, key, limit_seconds=600):
    now = time.time()
    attempts = store[key]
    while attempts and attempts[0] < now - limit_seconds:
        attempts.popleft()
    return attempts


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_authenticated"):
            return jsonify({"error": "Staff login required"}), 401
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(24)
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route("/api/bookings", methods=["POST"])
def create_booking():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    attempts = recent_attempts(booking_attempts, ip)
    if len(attempts) >= 12:
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    attempts.append(time.time())

    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    booking_date = str(data.get("date", "")).strip()
    booking_time = str(data.get("time", "")).strip()

    try:
        guests = int(data.get("guests", 0))
    except (TypeError, ValueError):
        guests = 0

    if not (2 <= len(name) <= 80):
        return jsonify({"error": "Enter a valid name."}), 400
    digits = "".join(character for character in phone if character.isdigit())
    if not (8 <= len(digits) <= 15):
        return jsonify({"error": "Enter a valid phone number."}), 400
    if not booking_date:
        return jsonify({"error": "Select a booking date."}), 400
    try:
        selected_date = date.fromisoformat(booking_date)
    except ValueError:
        return jsonify({"error": "Enter a valid booking date."}), 400
    if selected_date < date.today():
        return jsonify({"error": "The booking date cannot be in the past."}), 400
    if not booking_time:
        return jsonify({"error": "Select a booking time."}), 400
    if not (1 <= guests <= 20):
        return jsonify({"error": "Enter a valid guest count."}), 400

    with get_db() as db:
        cursor = db.execute("""
            INSERT INTO bookings
                (name, phone, booking_date, booking_time, guests, status, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?)
        """, (name, phone, booking_date, booking_time, guests, ip, datetime.utcnow().isoformat(timespec="seconds") + "Z"))
        booking_id = cursor.lastrowid

    return jsonify({"success": True, "id": booking_id}), 201


@app.route("/api/staff/login", methods=["POST"])
def staff_login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    attempts = recent_attempts(login_attempts, ip)
    if len(attempts) >= 5:
        return jsonify({"error": "Too many login attempts. Try again in 10 minutes."}), 429

    data = request.get_json(silent=True) or {}
    code = str(data.get("code", ""))
    if not check_password_hash(STAFF_CODE_HASH, code):
        attempts.append(time.time())
        return jsonify({"error": "Incorrect staff access code."}), 401

    login_attempts[ip].clear()
    session.clear()
    session.permanent = True
    session["staff_authenticated"] = True
    session["csrf_token"] = secrets.token_urlsafe(24)
    return jsonify({"success": True, "csrfToken": session["csrf_token"]})


@app.route("/api/staff/logout", methods=["POST"])
@staff_required
def staff_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/staff/session")
@staff_required
def staff_session():
    return jsonify({"success": True, "csrfToken": session["csrf_token"]})


@app.route("/api/staff/bookings")
@staff_required
def staff_bookings():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, name, phone, booking_date, booking_time, guests, status,
                   ip_address, created_at
            FROM bookings
            ORDER BY created_at DESC
        """).fetchall()
    return jsonify({"bookings": [dict(row) for row in rows]})


@app.route("/api/staff/bookings/<int:booking_id>", methods=["PATCH"])
@staff_required
def update_booking(booking_id):
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(csrf_token, session.get("csrf_token", "")):
        return jsonify({"error": "Invalid security token"}), 403

    data = request.get_json(silent=True) or {}
    status = str(data.get("status", ""))
    if status not in {"new", "confirmed", "cancelled"}:
        return jsonify({"error": "Invalid booking status"}), 400

    with get_db() as db:
        cursor = db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "Booking not found"}), 404
    return jsonify({"success": True})


@app.route("/api/staff/bookings/<int:booking_id>", methods=["DELETE"])
@staff_required
def delete_booking(booking_id):
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(csrf_token, session.get("csrf_token", "")):
        return jsonify({"error": "Invalid security token"}), 403

    with get_db() as db:
        cursor = db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        if cursor.rowcount == 0:
            return jsonify({"error": "Booking not found"}), 404
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500, debug=False)
