# КОД ДЛЯ РАБОТЫ САЙТА

import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
import sqlite3
from datetime import datetime, timedelta, date
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import calendar
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'database.db')
app = Flask(__name__)
app.secret_key = "your_secret_key_here"
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            is_done INTEGER DEFAULT 0,
            all_day INTEGER DEFAULT 0,
            attachment TEXT,
            tag TEXT,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """
    )

    try:
        c.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE users ADD COLUMN chat_id INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN reminded_hour INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN reminded_day INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


class User(UserMixin):
    def __init__(self, id_, username, password):
        self.id = id_
        self.username = username
        self.password = password


@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(id_=user[0], username=user[1], password=user[2])
    return None


@app.route("/")
@login_required
def index():
    search = request.args.get("search", "").strip()
    filter_status = request.args.get("filter")
    tag_filter = request.args.get("tag")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    query = "SELECT * FROM tasks WHERE user_id = ?"
    params = [current_user.id]

    if filter_status == "active":
        query += " AND is_done = 0"
    elif filter_status == "done":
        query += " AND is_done = 1"

    if search:
        query += " AND title LIKE ?"
        params.append(f"%{search}%")

    if tag_filter:
        query += " AND tag = ?"
        params.append(tag_filter)

    query += " ORDER BY is_done, due_date"

    c.execute(query, params)
    tasks = c.fetchall()
    processed_tasks = []
    today = datetime.today().date()

    for task in tasks:
        due_date_str = task[3]
        is_overdue = False
        is_due_soon = None

        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d %H:%M")
                if not task[4] and due_date < today:
                    is_overdue = True
                elif not task[4] and due_date == today:
                    is_due_soon = "Сегодня!"
                elif not task[4] and due_date == today + timedelta(days=1):
                    is_due_soon = "Завтра!"
            except ValueError:
                pass

        processed_tasks.append(
            {
                "id": task[0],
                "title": task[1],
                "description": task[2],
                "due_date": task[3],
                "is_done": task[4],
                "is_overdue": is_overdue,
                "due_soon": is_due_soon,
                "tag": task[7],
            }
        )

    return render_template("index.html", tasks=processed_tasks)


@app.route("/add", methods=["POST"])
@login_required
def add_task():
    title = request.form["title"]
    description = request.form.get("description", "")
    due_date = request.form.get("due_date", "")
    all_day = int(bool(request.form.get("all_day", False)))
    files = request.files.getlist("attachments")  # <-- получаем список файлов
    tag = request.form.get("tag", "").strip()

    filenames = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            os.makedirs("uploads", exist_ok=True)
            file.save(os.path.join("uploads", filename))
            filenames.append(filename)

    attachment_str = ";".join(filenames) if filenames else None

    if due_date and "T" not in due_date:
        due_date += "T23:59"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO tasks (title, description, due_date, all_day, attachment, tag, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (title, description, due_date, all_day, attachment_str, tag, current_user.id),
    )

    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/done/<int:task_id>")
def mark_done(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET is_done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/delete/<int:task_id>")
def delete_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == "POST":
        title = request.form["title"]
        description = request.form.get("description", "")
        due_date = request.form.get("due_date", "")
        all_day = int(bool(request.form.get("all_day", False)))

        c.execute("SELECT attachment FROM tasks WHERE id = ?", (task_id,))
        current_attachments_raw = c.fetchone()[0] or ""
        current_attachments = (
            current_attachments_raw.split(";") if current_attachments_raw else []
        )

        delete_attachments = request.form.getlist("delete_attachments")
        remaining_attachments = [
            f for f in current_attachments if f not in delete_attachments
        ]
        for filename in delete_attachments:
            path = os.path.join("uploads", filename)
            if os.path.exists(path):
                os.remove(path)

        new_files = request.files.getlist("attachments")
        for file in new_files:
            if file and file.filename:
                secure_name = secure_filename(file.filename)
                os.makedirs("uploads", exist_ok=True)
                file.save(os.path.join("uploads", secure_name))
                remaining_attachments.append(secure_name)

        attachment_string = ";".join(remaining_attachments)
        tag = request.form.get("tag", "").strip()

        c.execute(
            """
            UPDATE tasks
            SET title=?, description=?, due_date=?, all_day=?, attachment=?, tag=?
            WHERE id=? AND user_id=?
        """,
            (
                title,
                description,
                due_date,
                all_day,
                attachment_string,
                tag,
                task_id,
                current_user.id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    else:
        c.execute(
            "SELECT id, title, description, due_date, all_day, attachment, tag FROM tasks WHERE id = ?",
            (task_id,),
        )
        task = c.fetchone()
        attachments = task[5].split(";") if task[5] else []
        conn.close()
        return render_template("edit.html", task=task, task_attachments=attachments)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed_password),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Пользователь с таким именем уже существует"
        conn.close()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            login_user(User(id_=user[0], username=user[1], password=user[2]))
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Неверный логин или пароль")

    return render_template("login.html")



@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


def get_next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def get_prev_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


@app.route("/calendar")
@app.route("/calendar/<int:year>/<int:month>")
@login_required
def calendar_view(year=None, month=None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    month_name = MONTH_NAMES[month]

    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, title, due_date FROM tasks WHERE user_id = ?", (current_user.id,)
    )
    tasks = c.fetchall()
    conn.close()

    # Группируем задачи по дате
    tasks_by_day = {}
    for task in tasks:
        task_id, title, due_date = task
        if due_date:
            date_str = due_date.split("T")[0]
            tasks_by_day.setdefault(date_str, []).append(
                {"id": task_id, "title": title}
            )

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        month_name=month_name,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        calendar=month_days,
        tasks_by_day=tasks_by_day,
    )


@app.route("/calendar/<int:year>/<int:month>/<int:day>")
@login_required
def view_day(year, month, day):
    target_date = f"{year:04d}-{month:02d}-{day:02d}"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT id, title, description, due_date, is_done 
                 FROM tasks 
                 WHERE user_id = ? AND due_date LIKE ?""",
        (current_user.id, f"{target_date}%"),
    )
    tasks = c.fetchall()
    conn.close()
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    readable_date = f"{day} {month_names[month - 1]} {year} г."

    return render_template("day_view.html", tasks=tasks, date=readable_date)


@app.route("/view/<int:task_id>")
@login_required
def view_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, current_user.id)
    )
    task = c.fetchone()
    conn.close()

    if not task:
        return "Задача не найдена", 404

    task_data = {
        "id": task[0],
        "title": task[1],
        "description": task[2],
        "due_date": task[3],
        "is_done": task[4],
        "all_day": task[5],
        "attachment": task[6],
        "tag": task[7],
    }

    return render_template("view.html", task=task_data)


@app.route("/stats")
@login_required
def stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Всего задач
    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (current_user.id,))
    total_tasks = c.fetchone()[0]

    # Выполненные задачи
    c.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND is_done = 1",
        (current_user.id,),
    )
    done_tasks = c.fetchone()[0]

    # Невыполненные задачи
    c.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND is_done = 0",
        (current_user.id,),
    )
    not_done_tasks = c.fetchone()[0]

    # Задачи по категориям
    c.execute(
        "SELECT tag, COUNT(*) FROM tasks WHERE user_id = ? GROUP BY tag",
        (current_user.id,),
    )
    tag_counts = dict(c.fetchall())

    # Задачи по месяцам
    c.execute("SELECT due_date FROM tasks WHERE user_id = ?", (current_user.id,))
    rows = c.fetchall()
    monthly_counts = defaultdict(int)

    for row in rows:
        due_date = row[0]
        if due_date:
            try:
                if "T" in due_date:
                    date_obj = datetime.strptime(due_date, "%Y-%m-%dT%H:%M")
                elif " " in due_date:
                    date_obj = datetime.strptime(due_date, "%Y-%m-%d %H:%M")
                else:
                    date_obj = datetime.strptime(due_date, "%Y-%m-%d")
                key = date_obj.strftime("%Y-%m")
                monthly_counts[key] += 1
            except Exception as e:
                continue

    conn.close()
    return render_template(
        "stats.html",
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        not_done_tasks=not_done_tasks,
        tag_counts=tag_counts,
        monthly_counts=monthly_counts,
    )


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_name = request.form.get("name", "").strip()
        telegram_username = request.form.get("telegram_username", "").strip()

        if new_username:
            c.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (new_username, current_user.id),
            )
        if new_name:
            c.execute(
                "UPDATE users SET name = ? WHERE id = ?", (new_name, current_user.id)
            )
        if telegram_username:
            c.execute(
                "UPDATE users SET telegram_username = ? WHERE id = ?",
                (telegram_username, current_user.id),
            )

        conn.commit()
        conn.close()
        flash("Данные профиля обновлены", "success")
        return redirect(url_for("profile"))

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (current_user.id,)
    ).fetchone()
    conn.close()
    return render_template("profile.html", user=user)


@app.route("/update_name", methods=["POST"])
@login_required
def update_name():
    new_name = request.form["name"]
    conn = get_db_connection()
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, current_user.id))
    conn.commit()
    conn.close()
    flash("Имя успешно обновлено!")
    return redirect(url_for("profile"))


@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form["current_password"]
    new_password = request.form["new_password"]
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (current_user.id,)
    ).fetchone()

    if not check_password_hash(user["password"], current_password):
        flash("Текущий пароль неверен.")
        conn.close()
        return redirect(url_for("profile"))

    hashed_password = generate_password_hash(new_password)
    conn.execute(
        "UPDATE users SET password = ? WHERE id = ?", (hashed_password, current_user.id)
    )
    conn.commit()
    conn.close()
    flash("Пароль успешно изменён.")
    return redirect(url_for("profile"))


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (current_user.id,))
    conn.commit()
    conn.close()
    flash("Аккаунт удалён.")
    return redirect(url_for("logout"))


@app.route("/update_telegram", methods=["GET", "POST"])
@login_required
def update_telegram():
    success = False
    error = None

    if request.method == "POST":
        chat_id = request.form.get("chat_id", "").strip()
        if chat_id.isdigit():
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "UPDATE users SET chat_id = ? WHERE id = ?",
                (int(chat_id), current_user.id),
            )
            conn.commit()
            conn.close()
            success = True
        else:
            error = "⚠️ Неправильный формат Chat ID — только цифры."

    return render_template("update_telegram.html", success=success, error=error)



if __name__ == "__main__":
    init_db()
    app.run(debug=True)
