"""Демо-запуск без MySQL: тот же сайт на локальной SQLite.

Нужен, чтобы посмотреть/проверить проект там, где нет доступа к базе
(например, на домашнем компьютере). Код приложения при этом не меняется —
подменяется только подключение к БД.

Запуск:
    python demo_run.py
    # открыть http://127.0.0.1:5000
"""

import os
import re
import sqlite3
import sys

DEMO_DB = os.environ.get("DEMO_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.db"))

USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

TRANSACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    type TEXT NOT NULL DEFAULT 'deposit',
    cost REAL,
    description TEXT,
    balance_after REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class DemoCursor:
    """Обёртка над курсором sqlite3, повторяющая поведение mysql-connector."""

    def __init__(self, cur, dictionary=False):
        self._cur = cur
        self._dictionary = dictionary
        self.lastrowid = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        sql = self._translate(sql)
        try:
            self._cur.execute(sql, params or ())
        except sqlite3.IntegrityError as exc:
            # Приложению важно отличить «email уже занят» от прочих ошибок
            from mysql.connector import IntegrityError
            raise IntegrityError(str(exc)) from None
        self.lastrowid = self._cur.lastrowid
        self.rowcount = self._cur.rowcount

    @staticmethod
    def _translate(sql: str) -> str:
        head = sql.strip().upper()
        if head.startswith("CREATE TABLE") and "USERS" in head:
            return USERS_DDL
        if head.startswith("CREATE TABLE") and "TRANSACTIONS" in head:
            return TRANSACTIONS_DDL
        return re.sub(r"%s", "?", sql.replace("`", ""))

    def _row(self, row):
        if row is None or not self._dictionary:
            return row
        columns = [description[0] for description in self._cur.description]
        return dict(zip(columns, row))

    def fetchone(self):
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cur.fetchall()]

    def close(self):
        self._cur.close()


class DemoConnection:
    def __init__(self):
        self._cnx = sqlite3.connect(DEMO_DB, check_same_thread=False, timeout=10)

    def cursor(self, dictionary=False, buffered=False):
        return DemoCursor(self._cnx.cursor(), dictionary=dictionary)

    def commit(self):
        self._cnx.commit()

    def rollback(self):
        self._cnx.rollback()

    def close(self):
        self._cnx.close()


def demo_connect(*args, **kwargs):
    return DemoConnection()


def seed_demo_data() -> None:
    """Один демо-пользователь, чтобы было что посмотреть сразу."""
    from werkzeug.security import generate_password_hash

    cnx = DemoConnection()
    try:
        cur = cnx.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS total FROM users")
        if cur.fetchone()["total"]:
            return
        cur.execute(
            "INSERT INTO users (username, email, password_hash, balance) VALUES (?, ?, ?, ?)",
            ("Демо", "demo@demo.ru", generate_password_hash("demo123"), 1500.0),
        )
        user_id = cur.lastrowid
        for amount, description, balance_after in (
            (1000.0, "Пополнение баланса (демо)", 1000.0),
            (500.0, "Пополнение баланса (демо)", 1500.0),
        ):
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, cost, description, balance_after) "
                "VALUES (?, ?, 'deposit', NULL, ?, ?)",
                (user_id, amount, description, balance_after),
            )
        cnx.commit()
    finally:
        cnx.close()


def main() -> None:
    # Демо-режим: модель не грузим, иначе первый запрос полезет качать 400 МБ
    os.environ.setdefault("DEMO_MODE", "1")
    os.environ.setdefault("HOST", "0.0.0.0")
    os.environ.setdefault("PORT", "5000")

    import db

    db.connect = demo_connect

    import app as application

    db.init_schema()
    seed_demo_data()

    print(f"[DEMO] База: {DEMO_DB} (SQLite вместо MySQL)")
    print("[DEMO] Демо-аккаунт: demo@demo.ru / demo123")
    print(f"[DEMO] Сайт: http://127.0.0.1:{os.environ.get('PORT', '5000')}")

    application.app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        use_reloader=False,
    )


if __name__ == "__main__":
    sys.exit(main())
