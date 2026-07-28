import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, g, render_template, request, redirect, url_for,
                    session, flash)
from werkzeug.security import generate_password_hash, check_password_hash

from translations import LANGUAGES, TRANSLATIONS, t, lang_name

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hunarconnect.db")

SKILL_KEYS = ["SK_EMBROIDERY", "SK_TAILORING", "SK_CARPENTRY", "SK_PLUMBING",
              "SK_ELECTRICAL", "SK_PAINTING", "SK_CATERING"]
SKILL_SLUGS = ["embroidery", "tailoring", "carpentry", "plumbing",
               "electrical", "painting", "catering"]

app = Flask(__name__)
app.secret_key = os.environ.get("HUNARCONNECT_SECRET", "dev-secret-change-me")


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL CHECK(role IN ('owner', 'worker')),
            name TEXT NOT NULL,
            business_name TEXT,
            phone TEXT NOT NULL UNIQUE,
            email TEXT,
            password_hash TEXT NOT NULL,
            area TEXT NOT NULL,
            lang TEXT NOT NULL DEFAULT 'en',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS worker_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            skills TEXT NOT NULL DEFAULT '',
            about TEXT NOT NULL DEFAULT '',
            day_rate REAL,
            piece_rate REAL,
            languages_spoken TEXT NOT NULL DEFAULT '',
            rating_sum INTEGER NOT NULL DEFAULT 0,
            rating_count INTEGER NOT NULL DEFAULT 0,
            cancellations INTEGER NOT NULL DEFAULT 0,
            completed_jobs INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS owner_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            rating_sum INTEGER NOT NULL DEFAULT 0,
            rating_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            skill TEXT NOT NULL,
            area TEXT NOT NULL,
            price_type TEXT NOT NULL CHECK(price_type IN ('day', 'piece')),
            duration TEXT NOT NULL,
            trial INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open', 'active', 'completed', 'needs_attention')),
            worker_id INTEGER REFERENCES users(id),
            excluded_worker_ids TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_interests (
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            worker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (job_id, worker_id)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            from_user INTEGER NOT NULL REFERENCES users(id),
            to_user INTEGER NOT NULL REFERENCES users(id),
            stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
            comment TEXT,
            dispute INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, from_user)
        );
        """
    )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
@app.before_request
def ensure_language_selected():
    # Every route except the language picker and static files requires a
    # language to already be set in the session -- this is what "locks"
    # the app to one language before anything else (including login) shows.
    exempt = {"select_language", "static"}
    if request.endpoint in exempt or request.endpoint is None:
        return
    if "lang" not in session:
        return redirect(url_for("select_language", next=request.path))


@app.context_processor
def inject_globals():
    lang = session.get("lang", "en")
    return dict(
        _=lambda key, **kw: t(lang, key, **kw),
        current_lang=lang,
        current_lang_name=lang_name(lang),
        LANGUAGES=LANGUAGES,
        skill_list=list(zip(SKILL_SLUGS, SKILL_KEYS)),
        skill_key_map=dict(zip(SKILL_SLUGS, SKILL_KEYS)),
    )


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("landing"))
            if role and session.get("role") != role:
                return redirect(url_for("landing"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def reliability_badge(worker_row):
    cancellations = worker_row["cancellations"]
    completed = worker_row["completed_jobs"]
    if completed == 0 and cancellations == 0:
        return ("new", None)
    if cancellations > 0:
        return ("warning", None)
    return ("good", completed)


# --------------------------------------------------------------------------
# 1. Language selection (always first)
# --------------------------------------------------------------------------
@app.route("/language", methods=["GET", "POST"])
def select_language():
    if request.method == "POST":
        code = request.form.get("lang")
        valid_codes = {c for c, _ in LANGUAGES}
        if code in valid_codes:
            session["lang"] = code
            session.permanent = True
            nxt = request.args.get("next") or url_for("landing")
            return redirect(nxt)
    return render_template("language_select.html")


@app.route("/change-language", methods=["GET", "POST"])
def change_language():
    # Reachable from Edit Profile / dashboards; re-uses the same picker.
    return redirect(url_for("select_language", next=request.referrer or url_for("landing")))


# --------------------------------------------------------------------------
# 2. Landing
# --------------------------------------------------------------------------
@app.route("/")
def landing():
    if "user_id" in session:
        return redirect(url_for("owner_dashboard") if session["role"] == "owner"
                         else url_for("worker_dashboard"))
    return render_template("landing.html")


# --------------------------------------------------------------------------
# 3. Registration
# --------------------------------------------------------------------------
@app.route("/register/owner", methods=["GET", "POST"])
def register_owner():
    if request.method == "POST":
        db = get_db()
        name = request.form.get("name", "").strip()
        business_name = request.form.get("business_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        area = request.form.get("area", "").strip()

        if not all([name, business_name, phone, password, area]):
            flash(t(session["lang"], "REQUIRED_FIELD"), "error")
            return render_template("register_owner.html")

        existing = db.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if existing:
            flash(t(session["lang"], "PHONE_IN_USE"), "error")
            return render_template("register_owner.html")

        cur = db.execute(
            """INSERT INTO users (role, name, business_name, phone, email,
               password_hash, area, lang, created_at)
               VALUES ('owner', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, business_name, phone, email, generate_password_hash(password),
             area, session["lang"], datetime.utcnow().isoformat()),
        )
        db.execute("INSERT INTO owner_profiles (user_id) VALUES (?)", (cur.lastrowid,))
        db.commit()
        session["user_id"] = cur.lastrowid
        session["role"] = "owner"
        return redirect(url_for("owner_dashboard"))

    return render_template("register_owner.html")


@app.route("/register/worker", methods=["GET", "POST"])
def register_worker():
    if request.method == "POST":
        db = get_db()
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        area = request.form.get("area", "").strip()
        skills = request.form.getlist("skills")
        about = request.form.get("about", "").strip()
        day_rate = request.form.get("day_rate") or None
        piece_rate = request.form.get("piece_rate") or None
        languages_spoken = request.form.getlist("languages_spoken")

        if not all([name, phone, password, area]) or not skills:
            flash(t(session["lang"], "REQUIRED_FIELD"), "error")
            return render_template("register_worker.html")

        existing = db.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if existing:
            flash(t(session["lang"], "PHONE_IN_USE"), "error")
            return render_template("register_worker.html")

        cur = db.execute(
            """INSERT INTO users (role, name, phone, email, password_hash,
               area, lang, created_at)
               VALUES ('worker', ?, ?, ?, ?, ?, ?, ?)""",
            (name, phone, email, generate_password_hash(password), area,
             session["lang"], datetime.utcnow().isoformat()),
        )
        user_id = cur.lastrowid
        db.execute(
            """INSERT INTO worker_profiles
               (user_id, skills, about, day_rate, piece_rate, languages_spoken)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, ",".join(skills), about, day_rate, piece_rate,
             ",".join(languages_spoken)),
        )
        db.commit()
        session["user_id"] = user_id
        session["role"] = "worker"
        return redirect(url_for("worker_dashboard"))

    return render_template("register_worker.html")


# --------------------------------------------------------------------------
# 4. Login / logout
# --------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        user = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            return redirect(url_for("owner_dashboard") if user["role"] == "owner"
                             else url_for("worker_dashboard"))
        flash(t(session["lang"], "INVALID_LOGIN"), "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("role", None)
    return redirect(url_for("landing"))


# --------------------------------------------------------------------------
# 5. Owner dashboard + posting jobs
# --------------------------------------------------------------------------
@app.route("/owner", methods=["GET"])
@login_required(role="owner")
def owner_dashboard():
    db = get_db()
    jobs = db.execute(
        "SELECT * FROM jobs WHERE owner_id = ? ORDER BY created_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("owner_dashboard.html", jobs=jobs)


@app.route("/owner/post-job", methods=["GET", "POST"])
@login_required(role="owner")
def post_job():
    if request.method == "POST":
        db = get_db()
        skill = request.form.get("skill")
        area = request.form.get("area", "").strip()
        price_type = request.form.get("price_type")
        duration = request.form.get("duration", "").strip()
        trial = 1 if request.form.get("trial") else 0

        cur = db.execute(
            """INSERT INTO jobs (owner_id, skill, area, price_type, duration,
               trial, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (session["user_id"], skill, area, price_type, duration, trial,
             datetime.utcnow().isoformat()),
        )
        db.commit()
        return redirect(url_for("matches", job_id=cur.lastrowid))
    return render_template("post_job.html")


@app.route("/owner/jobs/<int:job_id>/matches")
@login_required(role="owner")
def matches(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND owner_id = ?",
                      (job_id, session["user_id"])).fetchone()
    if not job:
        return redirect(url_for("owner_dashboard"))

    excluded = set(filter(None, job["excluded_worker_ids"].split(",")))
    workers = db.execute(
        """SELECT u.*, wp.* FROM users u
           JOIN worker_profiles wp ON wp.user_id = u.id
           WHERE u.role = 'worker'""",
    ).fetchall()

    interested_ids = {r["worker_id"] for r in db.execute(
        "SELECT worker_id FROM job_interests WHERE job_id = ?", (job_id,))}

    candidates = []
    for w in workers:
        if str(w["id"]) in excluded:
            continue
        if job["skill"] not in (w["skills"] or "").split(","):
            continue
        avg = (w["rating_sum"] / w["rating_count"]) if w["rating_count"] else 0
        same_area = 1 if w["area"].strip().lower() == job["area"].strip().lower() else 0
        interested = 1 if w["id"] in interested_ids else 0
        badge_kind, n = reliability_badge(w)
        reliability_rank = {"good": 2, "new": 1, "warning": 0}[badge_kind]
        candidates.append({
            "row": w,
            "avg": round(avg, 1),
            "badge_kind": badge_kind,
            "badge_n": n,
            "interested": interested,
            "sort_key": (same_area, interested, reliability_rank, avg),
        })
    candidates.sort(key=lambda c: c["sort_key"], reverse=True)

    return render_template("matches.html", job=job, candidates=candidates)


@app.route("/owner/jobs/<int:job_id>/connect/<int:worker_id>", methods=["GET", "POST"])
@login_required(role="owner")
def connect(job_id, worker_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND owner_id = ?",
                      (job_id, session["user_id"])).fetchone()
    worker = db.execute(
        """SELECT u.*, wp.* FROM users u JOIN worker_profiles wp ON wp.user_id = u.id
           WHERE u.id = ?""", (worker_id,)).fetchone()
    if not job or not worker:
        return redirect(url_for("owner_dashboard"))

    if request.method == "POST":
        db.execute(
            "UPDATE jobs SET status = 'active', worker_id = ? WHERE id = ?",
            (worker_id, job_id),
        )
        db.commit()
        return redirect(url_for("owner_dashboard"))

    rate = worker["day_rate"] if job["price_type"] == "day" else worker["piece_rate"]
    return render_template("agreement.html", job=job, worker=worker, rate=rate)


@app.route("/owner/jobs/<int:job_id>/complete", methods=["GET", "POST"])
@login_required(role="owner")
def complete_job(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND owner_id = ?",
                      (job_id, session["user_id"])).fetchone()
    if not job or job["status"] != "active":
        return redirect(url_for("owner_dashboard"))

    if request.method == "POST":
        db.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
        db.execute(
            "UPDATE worker_profiles SET completed_jobs = completed_jobs + 1 WHERE user_id = ?",
            (job["worker_id"],),
        )
        # Optional rating from the owner, submitted in the same step
        stars = request.form.get("stars") if request.form.get("action") != "skip" else None
        if stars:
            dispute = 1 if request.form.get("dispute") else 0
            comment = request.form.get("comment", "").strip() or None
            db.execute(
                """INSERT OR IGNORE INTO ratings (job_id, from_user, to_user, stars,
                   comment, dispute, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, session["user_id"], job["worker_id"], int(stars),
                 comment, dispute, datetime.utcnow().isoformat()),
            )
            db.execute(
                """UPDATE worker_profiles SET rating_sum = rating_sum + ?,
                   rating_count = rating_count + 1 WHERE user_id = ?""",
                (int(stars), job["worker_id"]),
            )
        db.commit()
        return redirect(url_for("owner_dashboard"))

    worker = db.execute("SELECT * FROM users WHERE id = ?", (job["worker_id"],)).fetchone()
    return render_template("rate.html", job=job, other=worker, target="worker")


# --------------------------------------------------------------------------
# 6. Backup suggestion after a cancellation
# --------------------------------------------------------------------------
@app.route("/owner/jobs/<int:job_id>/find-backup")
@login_required(role="owner")
def find_backup(job_id):
    return redirect(url_for("matches", job_id=job_id))


# --------------------------------------------------------------------------
# 7. Worker dashboard, cancel, rate owner, job feed, apply
# --------------------------------------------------------------------------
@app.route("/worker")
@login_required(role="worker")
def worker_dashboard():
    db = get_db()
    jobs = db.execute(
        """SELECT jobs.*, u.name AS owner_name, u.business_name AS owner_business
           FROM jobs JOIN users u ON u.id = jobs.owner_id
           WHERE jobs.worker_id = ? ORDER BY jobs.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    already_rated = {r["job_id"] for r in db.execute(
        "SELECT job_id FROM ratings WHERE from_user = ?", (session["user_id"],))}
    return render_template("worker_dashboard.html", jobs=jobs, already_rated=already_rated)


@app.route("/worker/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required(role="worker")
def cancel_job(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND worker_id = ?",
                      (job_id, session["user_id"])).fetchone()
    if job and job["status"] == "active":
        excluded = set(filter(None, job["excluded_worker_ids"].split(",")))
        excluded.add(str(session["user_id"]))
        db.execute(
            """UPDATE jobs SET status = 'needs_attention', worker_id = NULL,
               excluded_worker_ids = ? WHERE id = ?""",
            (",".join(excluded), job_id),
        )
        db.execute(
            "UPDATE worker_profiles SET cancellations = cancellations + 1 WHERE user_id = ?",
            (session["user_id"],),
        )
        db.commit()
    return redirect(url_for("worker_dashboard"))


@app.route("/worker/jobs/<int:job_id>/rate-owner", methods=["GET", "POST"])
@login_required(role="worker")
def rate_owner(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ? AND worker_id = ? AND status = 'completed'",
                      (job_id, session["user_id"])).fetchone()
    if not job:
        return redirect(url_for("worker_dashboard"))

    if request.method == "POST":
        stars = request.form.get("stars") if request.form.get("action") != "skip" else None
        if stars:
            comment = request.form.get("comment", "").strip() or None
            db.execute(
                """INSERT OR IGNORE INTO ratings (job_id, from_user, to_user, stars,
                   comment, dispute, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (job_id, session["user_id"], job["owner_id"], int(stars), comment,
                 datetime.utcnow().isoformat()),
            )
            db.execute(
                """UPDATE owner_profiles SET rating_sum = rating_sum + ?,
                   rating_count = rating_count + 1 WHERE user_id = ?""",
                (int(stars), job["owner_id"]),
            )
            db.commit()
        return redirect(url_for("worker_dashboard"))

    owner = db.execute("SELECT * FROM users WHERE id = ?", (job["owner_id"],)).fetchone()
    return render_template("rate.html", job=job, other=owner, target="owner")


@app.route("/worker/feed")
@login_required(role="worker")
def job_feed():
    db = get_db()
    profile = db.execute("SELECT * FROM worker_profiles WHERE user_id = ?",
                          (session["user_id"],)).fetchone()
    my_skills = set(filter(None, (profile["skills"] or "").split(",")))
    open_jobs = db.execute(
        """SELECT jobs.*, u.business_name, u.name AS owner_name FROM jobs
           JOIN users u ON u.id = jobs.owner_id
           WHERE jobs.status = 'open' ORDER BY jobs.created_at DESC""",
    ).fetchall()
    matching = [j for j in open_jobs if j["skill"] in my_skills]
    applied_ids = {r["job_id"] for r in db.execute(
        "SELECT job_id FROM job_interests WHERE worker_id = ?", (session["user_id"],))}
    return render_template("job_feed.html", jobs=matching, applied_ids=applied_ids)


@app.route("/worker/feed/<int:job_id>/apply", methods=["POST"])
@login_required(role="worker")
def apply_to_job(job_id):
    db = get_db()
    db.execute("INSERT OR IGNORE INTO job_interests (job_id, worker_id) VALUES (?, ?)",
               (job_id, session["user_id"]))
    db.commit()
    return redirect(url_for("job_feed"))


# --------------------------------------------------------------------------
# 8. Edit profile (worker)
# --------------------------------------------------------------------------
@app.route("/worker/profile", methods=["GET", "POST"])
@login_required(role="worker")
def edit_profile():
    db = get_db()
    if request.method == "POST":
        area = request.form.get("area", "").strip()
        skills = request.form.getlist("skills")
        about = request.form.get("about", "").strip()
        day_rate = request.form.get("day_rate") or None
        piece_rate = request.form.get("piece_rate") or None
        languages_spoken = request.form.getlist("languages_spoken")

        db.execute("UPDATE users SET area = ? WHERE id = ?", (area, session["user_id"]))
        db.execute(
            """UPDATE worker_profiles SET skills = ?, about = ?, day_rate = ?,
               piece_rate = ?, languages_spoken = ? WHERE user_id = ?""",
            (",".join(skills), about, day_rate, piece_rate,
             ",".join(languages_spoken), session["user_id"]),
        )
        db.commit()
        return redirect(url_for("worker_dashboard"))

    user = current_user()
    profile = db.execute("SELECT * FROM worker_profiles WHERE user_id = ?",
                          (session["user_id"],)).fetchone()
    return render_template("edit_profile.html", user=user, profile=profile)


if not os.path.exists(DB_PATH):
    init_db()
else:
    init_db()  # idempotent, CREATE TABLE IF NOT EXISTS

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
