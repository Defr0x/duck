"""Подключение к MySQL и схема БД.

Доступы к базе лежат прямо в коде — так же, как в примере и в присланном
app.py (школьный хостинг sch688_vvedenie). Если понадобится другой сервер,
правь DB_CONFIG ниже.
"""

import logging

import mysql.connector
from mysql.connector import Error as MySQLError

logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "185.114.247.43",
    "port": 3306,
    "database": "sch688_vvedenie",
    "user": "sch688_vvedenie",
    "password": "Qwerty123",
    # Чтобы страница не висела минуту, если база недоступна
    "connection_timeout": 10,
}

# ---------------------------------------------------------------------------
# Схема. Если таблиц ещё нет — создастся при старте сервера.
# ---------------------------------------------------------------------------

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(50) NOT NULL,
    `email` VARCHAR(120) NOT NULL UNIQUE,
    `password_hash` VARCHAR(255) NOT NULL,
    `balance` DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS `transactions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `amount` DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    `type` VARCHAR(20) NOT NULL DEFAULT 'deposit',
    `cost` DECIMAL(10, 2) NULL,
    `description` VARCHAR(255) NULL,
    `balance_after` DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_transactions_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def connect():
    """Новое подключение к MySQL (в демо-режиме подменяется на SQLite)."""
    return mysql.connector.connect(**DB_CONFIG)


def init_schema() -> None:
    """Создаёт таблицы users и transactions, если их ещё нет."""
    try:
        cnx = connect()
        try:
            cur = cnx.cursor()
            try:
                cur.execute(CREATE_USERS)
                cur.execute(CREATE_TRANSACTIONS)
                cnx.commit()
            finally:
                cur.close()
        finally:
            cnx.close()
    except MySQLError as exc:
        logger.warning("Не удалось проверить схему БД: %s", exc)
