import json
import os
import random
import time
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db, init_db


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "")
    if not app.secret_key:
        raise RuntimeError("SECRET_KEY must be set via environment variables.")

    init_db()

    @app.before_request
    def load_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            db = get_db()
            result = db.execute("SELECT id, name, email FROM users WHERE id = ?", [user_id])
            g.user = result.rows[0] if result.rows else None

    def login_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped_view

    def admin_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            admin_emails = {
                email.strip().lower()
                for email in os.environ.get("ADMIN_EMAILS", "").split(",")
                if email.strip()
            }
            if g.user[2].lower() not in admin_emails:
                flash("Admin access required.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped_view

    @app.route("/")
    def index():
        if g.user:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not name or not email or not password:
                flash("All fields are required.", "error")
                return render_template("signup.html")

            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", [email])
            if existing.rows:
                flash("Email already registered.", "error")
                return render_template("signup.html")

            db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                [name, email, generate_password_hash(password)],
            )
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            db = get_db()
            result = db.execute("SELECT id, password_hash FROM users WHERE email = ?", [email])
            if not result.rows or not check_password_hash(result.rows[0][1], password):
                flash("Invalid credentials.", "error")
                return render_template("login.html")
            session.clear()
            session["user_id"] = result.rows[0][0]
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        db = get_db()
        subjects = db.execute("SELECT id, name FROM subjects ORDER BY name").rows
        subject_counts = db.execute(
            "SELECT subject_id, COUNT(*) FROM mcqs GROUP BY subject_id"
        ).rows
        subject_totals = {row[0]: row[1] for row in subject_counts}
        total_questions = sum(subject_totals.values())
        attempts = db.execute(
            "SELECT COUNT(*), SUM(correct_count), SUM(incorrect_count) FROM exam_attempts WHERE user_id = ?",
            [g.user[0]],
        ).rows[0]
        attempted = attempts[0] or 0
        correct = attempts[1] or 0
        incorrect = attempts[2] or 0
        accuracy = round((correct / max(correct + incorrect, 1)) * 100)
        improvement = "Keep practicing to build momentum." if attempted < 3 else "Stable improvement noted."
        return render_template(
            "dashboard.html",
            subjects=subjects,
            subject_totals=subject_totals,
            total_questions=total_questions,
            attempted=attempted,
            correct=correct,
            incorrect=incorrect,
            accuracy=accuracy,
            improvement=improvement,
        )

    @app.route("/admin/subjects", methods=["GET", "POST"])
    @admin_required
    def admin_subjects():
        db = get_db()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Subject name required.", "error")
            else:
                db.execute("INSERT INTO subjects (name) VALUES (?)", [name])
                flash("Subject added.", "success")
            return redirect(url_for("admin_subjects"))
        subjects = db.execute("SELECT id, name FROM subjects ORDER BY name").rows
        return render_template("admin_subjects.html", subjects=subjects)

    @app.post("/admin/subjects/<int:subject_id>/delete")
    @admin_required
    def delete_subject(subject_id):
        db = get_db()
        db.execute("DELETE FROM subjects WHERE id = ?", [subject_id])
        flash("Subject deleted.", "success")
        return redirect(url_for("admin_subjects"))

    @app.post("/admin/subjects/<int:subject_id>/rename")
    @admin_required
    def rename_subject(subject_id):
        name = request.form.get("name", "").strip()
        if not name:
            flash("Subject name required.", "error")
            return redirect(url_for("admin_subjects"))
        db = get_db()
        db.execute("UPDATE subjects SET name = ? WHERE id = ?", [name, subject_id])
        flash("Subject updated.", "success")
        return redirect(url_for("admin_subjects"))

    @app.route("/admin/mcqs")
    @admin_required
    def admin_mcqs():
        db = get_db()
        page = max(int(request.args.get("page", 1)), 1)
        offset = (page - 1) * 100
        mcqs = db.execute(
            "SELECT mcqs.id, subjects.name, mcqs.question FROM mcqs "
            "LEFT JOIN subjects ON mcqs.subject_id = subjects.id "
            "ORDER BY mcqs.id DESC LIMIT 100 OFFSET ?",
            [offset],
        ).rows
        total = db.execute("SELECT COUNT(*) FROM mcqs").rows[0][0]
        total_pages = max((total + 99) // 100, 1)
        return render_template(
            "admin_mcqs.html",
            mcqs=mcqs,
            page=page,
            total_pages=total_pages,
        )

    @app.route("/admin/mcqs/new", methods=["GET", "POST"])
    @admin_required
    def new_mcq():
        db = get_db()
        subjects = db.execute("SELECT id, name FROM subjects ORDER BY name").rows
        if request.method == "POST":
            payload = {
                "subject_id": request.form.get("subject_id"),
                "question": request.form.get("question", "").strip(),
                "option_a": request.form.get("option_a", "").strip(),
                "option_b": request.form.get("option_b", "").strip(),
                "option_c": request.form.get("option_c", "").strip(),
                "option_d": request.form.get("option_d", "").strip(),
                "correct_option": request.form.get("correct_option", "").strip(),
            }
            if not payload["subject_id"] or not payload["question"]:
                flash("Subject and question are required.", "error")
            else:
                db.execute(
                    "INSERT INTO mcqs (subject_id, question, option_a, option_b, option_c, option_d, correct_option) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        payload["subject_id"],
                        payload["question"],
                        payload["option_a"],
                        payload["option_b"],
                        payload["option_c"],
                        payload["option_d"],
                        payload["correct_option"],
                    ],
                )
                flash("MCQ added.", "success")
                return redirect(url_for("admin_mcqs"))
        return render_template("mcq_form.html", subjects=subjects, mcq=None)

    @app.route("/admin/mcqs/<int:mcq_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_mcq(mcq_id):
        db = get_db()
        subjects = db.execute("SELECT id, name FROM subjects ORDER BY name").rows
        mcq = db.execute(
            "SELECT id, subject_id, question, option_a, option_b, option_c, option_d, correct_option "
            "FROM mcqs WHERE id = ?",
            [mcq_id],
        ).rows
        if not mcq:
            flash("MCQ not found.", "error")
            return redirect(url_for("admin_mcqs"))
        mcq = mcq[0]
        if request.method == "POST":
            db.execute(
                "UPDATE mcqs SET subject_id = ?, question = ?, option_a = ?, option_b = ?, option_c = ?, "
                "option_d = ?, correct_option = ? WHERE id = ?",
                [
                    request.form.get("subject_id"),
                    request.form.get("question", "").strip(),
                    request.form.get("option_a", "").strip(),
                    request.form.get("option_b", "").strip(),
                    request.form.get("option_c", "").strip(),
                    request.form.get("option_d", "").strip(),
                    request.form.get("correct_option", "").strip(),
                    mcq_id,
                ],
            )
            flash("MCQ updated.", "success")
            return redirect(url_for("admin_mcqs"))
        return render_template("mcq_form.html", subjects=subjects, mcq=mcq)

    @app.post("/admin/mcqs/<int:mcq_id>/delete")
    @admin_required
    def delete_mcq(mcq_id):
        db = get_db()
        db.execute("DELETE FROM mcqs WHERE id = ?", [mcq_id])
        flash("MCQ deleted.", "success")
        return redirect(url_for("admin_mcqs"))

    @app.route("/admin/imports", methods=["GET", "POST"])
    @admin_required
    def import_batches():
        db = get_db()
        if request.method == "POST":
            file = request.files.get("payload")
            if not file:
                flash("JSON file required.", "error")
                return redirect(url_for("import_batches"))
            content = json.load(file)
            if not isinstance(content, list):
                flash("JSON must be a list of MCQs.", "error")
                return redirect(url_for("import_batches"))
            batch = db.execute(
                "INSERT INTO import_batches (filename) VALUES (?) RETURNING id",
                [file.filename],
            ).rows[0][0]
            items = []
            for entry in content:
                if not isinstance(entry, dict):
                    continue
                items.append(
                    [
                        entry.get("subject_id"),
                        entry.get("question"),
                        entry.get("option_a"),
                        entry.get("option_b"),
                        entry.get("option_c"),
                        entry.get("option_d"),
                        entry.get("correct_option"),
                        batch,
                    ]
                )
            if items:
                db.executemany(
                    "INSERT INTO mcqs (subject_id, question, option_a, option_b, option_c, option_d, correct_option, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    items,
                )
            flash("Import completed.", "success")
            return redirect(url_for("import_batches"))
        batches = db.execute(
            "SELECT id, filename, created_at FROM import_batches ORDER BY created_at DESC"
        ).rows
        return render_template("import_batches.html", batches=batches)

    @app.post("/admin/imports/<int:batch_id>/delete")
    @admin_required
    def delete_import(batch_id):
        db = get_db()
        db.execute("DELETE FROM mcqs WHERE batch_id = ?", [batch_id])
        db.execute("DELETE FROM import_batches WHERE id = ?", [batch_id])
        flash("Import batch deleted.", "success")
        return redirect(url_for("import_batches"))

    @app.route("/exam/setup", methods=["GET", "POST"])
    @login_required
    def exam_setup():
        db = get_db()
        subjects = db.execute("SELECT id, name FROM subjects ORDER BY name").rows
        if request.method == "POST":
            selected = request.form.getlist("subjects")
            mode = request.form.get("mode", "random")
            limit = min(int(request.form.get("count", 10)), 100)
            time_limit = max(int(request.form.get("time_limit", 15)), 5)
            question_rows = []
            if selected:
                placeholders = ",".join(["?"] * len(selected))
                question_rows = db.execute(
                    f"SELECT id FROM mcqs WHERE subject_id IN ({placeholders})",
                    selected,
                ).rows
            else:
                question_rows = db.execute("SELECT id FROM mcqs").rows
            ids = [row[0] for row in question_rows]
            if not ids:
                flash("No questions available for selection.", "error")
                return redirect(url_for("exam_setup"))
            if mode == "progress":
                random.shuffle(ids)
            else:
                random.shuffle(ids)
            selected_ids = ids[:limit]
            session["exam"] = {
                "question_ids": selected_ids,
                "start_time": int(time.time()),
                "time_limit": time_limit * 60,
                "answers": {},
            }
            return redirect(url_for("exam_question", index=0))
        return render_template("exam_setup.html", subjects=subjects)

    @app.route("/exam/<int:index>", methods=["GET", "POST"])
    @login_required
    def exam_question(index):
        exam = session.get("exam")
        if not exam:
            return redirect(url_for("exam_setup"))
        question_ids = exam.get("question_ids", [])
        if index < 0 or index >= len(question_ids):
            return redirect(url_for("exam_result"))
        if request.method == "POST":
            selected_option = request.form.get("answer")
            exam["answers"][str(question_ids[index])] = selected_option
            session["exam"] = exam
            if "next" in request.form:
                return redirect(url_for("exam_question", index=index + 1))
            if "prev" in request.form:
                return redirect(url_for("exam_question", index=index - 1))
            if "submit" in request.form:
                return redirect(url_for("exam_result"))
        db = get_db()
        question = db.execute(
            "SELECT id, question, option_a, option_b, option_c, option_d FROM mcqs WHERE id = ?",
            [question_ids[index]],
        ).rows
        if not question:
            return redirect(url_for("exam_result"))
        return render_template(
            "exam_question.html",
            question=question[0],
            index=index,
            total=len(question_ids),
            exam=exam,
        )

    @app.route("/exam/result")
    @login_required
    def exam_result():
        exam = session.pop("exam", None)
        if not exam:
            return redirect(url_for("dashboard"))
        db = get_db()
        question_ids = exam.get("question_ids", [])
        answers = exam.get("answers", {})
        if not question_ids:
            return redirect(url_for("dashboard"))
        placeholders = ",".join(["?"] * len(question_ids))
        rows = db.execute(
            f"SELECT id, question, option_a, option_b, option_c, option_d, correct_option FROM mcqs WHERE id IN ({placeholders})",
            question_ids,
        ).rows
        correct = 0
        review = []
        for row in rows:
            selected = answers.get(str(row[0]))
            is_correct = selected == row[6]
            correct += 1 if is_correct else 0
            review.append(
                {
                    "question": row[1],
                    "options": {
                        "A": row[2],
                        "B": row[3],
                        "C": row[4],
                        "D": row[5],
                    },
                    "correct": row[6],
                    "selected": selected,
                }
            )
        total = len(question_ids)
        incorrect = total - correct
        accuracy = round((correct / max(total, 1)) * 100)
        db.execute(
            "INSERT INTO exam_attempts (user_id, total_questions, correct_count, incorrect_count, accuracy) "
            "VALUES (?, ?, ?, ?, ?)",
            [g.user[0], total, correct, incorrect, accuracy],
        )
        return render_template(
            "exam_result.html",
            total=total,
            correct=correct,
            incorrect=incorrect,
            accuracy=accuracy,
            review=review,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
