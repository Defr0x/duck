"""НейроЧат — сайт с регистрацией, личным кабинетом, балансом,
чатом с локальной нейросетью и историей транзакций.

Запуск: python app.py  →  http://127.0.0.1:5000
Без MySQL (проверка/превью): python demo_run.py
"""

import hashlib
import logging
import os
import re
from contextlib import closing
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from jinja2 import TemplateNotFound
from mysql.connector import Error as MySQLError
from mysql.connector import IntegrityError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

try:  # .env не обязателен: если файла или пакета нет — берём окружение как есть
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import db
import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Постоянный ключ: сессии не слетают при перезапуске сервера.
app.secret_key = os.environ.get("SECRET_KEY", "neurochat-secret-key-change-me-2026")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 6
MAX_CHAT_MESSAGE = 2000
MAX_HISTORY = 10


# ============ Вспомогательные функции ============

def fmt_money(value) -> str:
    """1000 → '1 000,00'."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:,.2f}".replace(",", " ").replace(".", ",")


def fmt_date(value) -> str:
    """Дата из MySQL (datetime) или из демо-базы (строка) → 'ДД.ММ.ГГГГ ЧЧ:ММ'."""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    raw = str(value or "")[:16]
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        date_part = ".".join(reversed(raw[:10].split("-")))
        return f"{date_part} {raw[11:16]}".strip()
    return raw or "—"


def is_legacy_hash(stored: str) -> bool:
    """Старые пароли в базе — обычный SHA-256 (64 hex-символа)."""
    return bool(stored) and len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)


def verify_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    if is_legacy_hash(stored_hash):
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash
    try:
        return check_password_hash(stored_hash, password)
    except ValueError:
        return False


def find_user_by_id(user_id: int):
    with closing(db.connect()) as cnx, closing(cnx.cursor(dictionary=True)) as cur:
        cur.execute(
            "SELECT `id`, `username`, `email`, `balance` FROM `users` WHERE `id` = %s",
            (user_id,),
        )
        return cur.fetchone()


def find_user_by_email(email: str):
    with closing(db.connect()) as cnx, closing(cnx.cursor(dictionary=True)) as cur:
        cur.execute(
            "SELECT `id`, `username`, `email`, `password_hash`, `balance` "
            "FROM `users` WHERE `email` = %s",
            (email,),
        )
        return cur.fetchone()


def get_transactions(user_id: int):
    with closing(db.connect()) as cnx, closing(cnx.cursor(dictionary=True)) as cur:
        cur.execute(
            """SELECT `id`, `amount`, `type`, `cost`, `description`, `balance_after`, `created_at`
               FROM `transactions`
               WHERE `user_id` = %s
               ORDER BY `created_at` DESC, `id` DESC""",
            (user_id,),
        )
        rows = cur.fetchall()
    for row in rows:
        row["date"] = fmt_date(row.get("created_at"))
        row["amount_fmt"] = fmt_money(row.get("amount"))
        row["balance_fmt"] = fmt_money(row.get("balance_after"))
        row["is_income"] = str(row.get("type")) in ("deposit", "refund")
    return rows


def current_user():
    """Пользователь из сессии (свежие данные из БД) или None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        user = find_user_by_id(user_id)
    except MySQLError:
        logger.exception("Ошибка БД при чтении пользователя #%s", user_id)
        return None
    if not user:
        session.clear()
    return user


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.context_processor
def inject_globals():
    return {"fmt_money": fmt_money}


def explain_error(exc: Exception) -> str:
    """Человеческая подсказка к типичным ошибкам — чтобы не гадать по 500."""
    if isinstance(exc, TemplateNotFound):
        return (
            f"Не найден шаблон «{exc.name}». Проверь, что папка templates лежит рядом "
            "с app.py и в ней есть base.html, login.html, registration.html, "
            "profile.html, transactions.html."
        )
    if isinstance(exc, UnicodeDecodeError):
        return (
            "Файл сохранён не в UTF-8. Открой его в редакторе и сохрани как "
            "«UTF-8» (без BOM)."
        )
    if isinstance(exc, ModuleNotFoundError):
        return (
            f"Не установлен пакет «{exc.name}». Установи зависимости: "
            "pip install -r requirements.txt"
        )
    if isinstance(exc, MySQLError):
        return (
            "Не удалось выполнить запрос к MySQL. Проверь доступы в db.py "
            "(host, база, логин, пароль) и что таблицы users/transactions существуют."
        )
    if isinstance(exc, FileNotFoundError):
        return "Не найден файл. Проверь структуру папок проекта."
    return "Подробности — в терминале, где запущен python app.py (там печатается traceback)."


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    logger.exception("Необработанная ошибка на %s", request.path)
    return (
        render_template(
            "error.html",
            error_type=type(exc).__name__,
            error_text=str(exc),
            hint=explain_error(exc),
            path=request.path,
        ),
        500,
    )


# ============ Страницы ============

@app.route("/")
def index():
    return redirect(url_for("profile_page") if session.get("user_id") else url_for("login_page"))


@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("profile_page"))
    return render_template("login.html")


@app.route("/register")
def register_page():
    if session.get("user_id"):
        return redirect(url_for("profile_page"))
    return render_template("registration.html")


@app.route("/profile")
def profile_page():
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))
    return render_template(
        "profile.html",
        user=user,
        balance=fmt_money(user["balance"]),
        model_ready=llm.model.ready,
        demo_mode=llm.DEMO_MODE,
    )


@app.route("/transactions")
def transactions_page():
    user = current_user()
    if not user:
        return redirect(url_for("login_page"))
    try:
        transactions = get_transactions(user["id"])
    except MySQLError:
        logger.exception("Ошибка БД при загрузке транзакций")
        return render_template("transactions.html", transactions=[], error="База данных недоступна, попробуй позже."), 503
    return render_template("transactions.html", transactions=transactions)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ============ API: регистрация и вход ============

@app.route("/api/register", methods=["POST"])
@app.route("/user_register", methods=["POST"])  # совместимость со старым адресом
def user_register():
    req = request.get_json(silent=True) or {}

    name = str(req.get("name", "")).strip()
    email = str(req.get("email", "")).strip().lower()
    password = str(req.get("password", ""))

    if not name or not email or not password:
        return jsonify({"error": "Заполни все поля"}), 400
    if len(name) > 50:
        return jsonify({"error": "Имя длиннее 50 символов"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Похоже, email указан неверно"}), 400
    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": f"Пароль должен быть не короче {MIN_PASSWORD_LEN} символов"}), 400

    try:
        with closing(db.connect()) as cnx:
            with closing(cnx.cursor()) as cur:
                cur.execute(
                    "INSERT INTO `users` (`username`, `email`, `password_hash`, `balance`) "
                    "VALUES (%s, %s, %s, 0.00)",
                    (name, email, generate_password_hash(password)),
                )
                cnx.commit()
                user_id = cur.lastrowid
    except IntegrityError:
        return jsonify({"error": "Этот email уже зарегистрирован"}), 409
    except MySQLError:
        logger.exception("Ошибка БД при регистрации")
        return jsonify({"error": "База данных недоступна, попробуй позже"}), 500

    session.clear()
    session["user_id"] = user_id
    session["username"] = name
    return jsonify({"success": True, "redirect_url": "/profile"}), 201


@app.route("/api/login", methods=["POST"])
@app.route("/user_login", methods=["POST"])  # совместимость со старым адресом
def user_login():
    req = request.get_json(silent=True) or {}

    email = str(req.get("email", "")).strip().lower()
    password = str(req.get("password", ""))

    if not email or not password:
        return jsonify({"error": "Заполни email и пароль"}), 400

    try:
        user = find_user_by_email(email)
    except MySQLError:
        logger.exception("Ошибка БД при входе")
        return jsonify({"error": "База данных недоступна, попробуй позже"}), 500

    if not user or not verify_password(user["password_hash"], password):
        return jsonify({"error": "Неверный email или пароль"}), 401

    # Старый SHA-256 из прежней версии сайта — молча обновляем на PBKDF2
    if is_legacy_hash(user["password_hash"]):
        try:
            with closing(db.connect()) as cnx, closing(cnx.cursor()) as cur:
                cur.execute(
                    "UPDATE `users` SET `password_hash` = %s WHERE `id` = %s",
                    (generate_password_hash(password), user["id"]),
                )
                cnx.commit()
        except MySQLError:
            logger.warning("Не удалось обновить старый хэш пароля пользователя #%s", user["id"])

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"success": True, "redirect_url": "/profile"})


# ============ API: баланс ============

@app.route("/api/me")
def api_me():
    user = current_user()
    if not user:
        return jsonify({"error": "Нужно войти в аккаунт"}), 401
    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "balance": fmt_money(user["balance"]),
    })


@app.route("/api/topup", methods=["POST"])
def topup():
    """Демо-пополнение баланса и запись в историю транзакций."""
    user = current_user()
    if not user:
        return jsonify({"error": "Нужно войти в аккаунт"}), 401

    req = request.get_json(silent=True) or {}
    try:
        amount = round(float(req.get("amount", 0)), 2)
    except (TypeError, ValueError):
        amount = 0.0
    if amount < 10 or amount > 50000:
        return jsonify({"error": "Сумма пополнения — от 10 до 50 000 ₽"}), 400

    try:
        with closing(db.connect()) as cnx:
            with closing(cnx.cursor(dictionary=True)) as cur:
                cur.execute(
                    "UPDATE `users` SET `balance` = `balance` + %s WHERE `id` = %s",
                    (amount, user["id"]),
                )
                cnx.commit()
                cur.execute("SELECT `balance` FROM `users` WHERE `id` = %s", (user["id"],))
                balance = cur.fetchone()["balance"]
                cur.execute(
                    """INSERT INTO `transactions`
                       (`user_id`, `amount`, `type`, `cost`, `description`, `balance_after`)
                       VALUES (%s, %s, 'deposit', NULL, %s, %s)""",
                    (user["id"], amount, "Пополнение баланса (демо)", balance),
                )
                cnx.commit()
    except MySQLError:
        logger.exception("Ошибка БД при пополнении баланса")
        return jsonify({"error": "База данных недоступна, попробуй позже"}), 500

    return jsonify({"success": True, "balance": fmt_money(balance), "amount": fmt_money(amount)})


@app.route("/api/ping")
def api_ping():
    """Быстрая проверка: сервер жив и база отвечает?"""
    result = {"server": True, "db": False, "db_error": None}
    try:
        with closing(db.connect()) as cnx, closing(cnx.cursor()) as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        result["db"] = True
    except MySQLError as exc:
        result["db_error"] = str(exc)
        logger.warning("Проверка связи: база недоступна: %s", exc)
    return jsonify(result), 200 if result["db"] else 503


# ============ API: чат с нейросетью ============

@app.route("/api/chat/status")
def chat_status():
    status = llm.model.status()
    status["hint"] = llm.HINT
    status["demo"] = llm.DEMO_MODE
    return jsonify(status)


@app.route("/api/chat", methods=["POST"])
def chat():
    if not session.get("user_id"):
        return jsonify({"error": "Нужно войти в аккаунт"}), 401

    req = request.get_json(silent=True) or {}
    message = str(req.get("message", "")).strip()
    if not message:
        return jsonify({"error": "Сообщение пустое"}), 400
    if len(message) > MAX_CHAT_MESSAGE:
        return jsonify({"error": f"Сообщение длиннее {MAX_CHAT_MESSAGE} символов"}), 400

    history = []
    raw_history = req.get("history")
    if isinstance(raw_history, list):
        for item in raw_history[-MAX_HISTORY:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()[:MAX_CHAT_MESSAGE]
            if not content:
                continue
            history.append({
                "role": "assistant" if item.get("role") == "assistant" else "user",
                "content": content,
            })

    messages = history + [{"role": "user", "content": message}]

    if llm.DEMO_MODE:
        return jsonify({"reply": llm.demo_reply(message), "model": "demo"})

    status = llm.model.status()
    if not status["ready"] and status["loading"]:
        return jsonify({
            "error": "Модель ещё загружается — это занимает до пары минут при первом запуске.",
            "pending": True,
        }), 202
    if not status["ready"]:
        return jsonify({
            "error": status["error"] or "Нейросеть не подключена.",
            "hint": llm.HINT,
        }), 503

    try:
        reply = llm.model.generate(messages)
    except llm.ModelUnavailable as exc:
        return jsonify({"error": str(exc), "hint": llm.HINT}), 503
    except Exception:
        logger.exception("Ошибка генерации")
        return jsonify({"error": "Модель не смогла ответить, попробуй ещё раз"}), 500

    return jsonify({"reply": reply, "model": llm.MODEL_FILE})


# ============ Запуск ============

def init_db() -> None:
    db.init_schema()


def run(host=None, port=None, debug=None, warmup=True) -> None:
    init_db()
    if warmup:
        llm.model.warmup_async()
    app.run(
        host=host or os.environ.get("HOST", "127.0.0.1"),
        port=int(port or os.environ.get("PORT", "5000")),
        debug=(os.environ.get("FLASK_DEBUG") == "1") if debug is None else debug,
    )


if __name__ == "__main__":
    run()
