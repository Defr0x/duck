"""Работа с балансом пользователей в MySQL.

Примеры:
    python balance_tool.py                      # список всех аккаунтов и балансов
    python balance_tool.py set 1@1.ru 1000      # поставить баланс 1000 ₽
    python balance_tool.py add 1@1.ru 500       # начислить +500 ₽
    python balance_tool.py sync 1@1.ru          # пересчитать баланс из истории транзакций

Каждое изменение пишется в таблицу transactions, чтобы история не расходилась
с балансом.
"""

import sys

import db

TYPE_LABELS = {
    "deposit": "пополнение",
    "refund": "возврат",
    "purchase": "покупка",
    "withdraw": "списание",
}


def fmt_money(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:,.2f}".replace(",", " ").replace(".", ",")


def connect():
    print(f"База: host={db.DB_CONFIG['host']} / {db.DB_CONFIG['database']}\n")
    return db.connect()


def list_users(cur) -> None:
    cur.execute("SELECT `id`, `username`, `email`, `balance` FROM `users` ORDER BY `id`")
    rows = cur.fetchall()
    if not rows:
        print("В таблице users пока нет ни одного аккаунта.")
        return

    print(f"{'id':>4}  {'email':<28} {'имя':<18} {'баланс':>12}")
    print("-" * 66)
    for row in rows:
        print(
            f"{row['id']:>4}  {str(row['email'])[:28]:<28} "
            f"{str(row['username'])[:18]:<18} {fmt_money(row['balance']):>12} ₽"
        )
    print(f"\nВсего аккаунтов: {len(rows)}")


def find_user(cur, email: str):
    cur.execute(
        "SELECT `id`, `username`, `email`, `balance` FROM `users` WHERE `email` = %s",
        (email.strip().lower(),),
    )
    return cur.fetchone()


def write_transaction(cur, user_id: int, amount: float, type_: str, description: str, balance_after: float) -> None:
    cur.execute(
        """INSERT INTO `transactions`
           (`user_id`, `amount`, `type`, `cost`, `description`, `balance_after`)
           VALUES (%s, %s, %s, NULL, %s, %s)""",
        (user_id, amount, type_, description, balance_after),
    )


def set_balance(cur, email: str, amount: float, description: str) -> None:
    user = find_user(cur, email)
    if not user:
        print(f"Аккаунт {email} не найден. Запусти без аргументов — увидишь список.")
        sys.exit(1)

    old = float(user["balance"] or 0)
    cur.execute("UPDATE `users` SET `balance` = %s WHERE `id` = %s", (amount, user["id"]))
    write_transaction(
        cur, user["id"], abs(amount - old), "deposit" if amount >= old else "withdraw",
        description, amount,
    )
    print(f"{user['email']}: баланс {fmt_money(old)} ₽ → {fmt_money(amount)} ₽")


def sync_balance(cur, email: str) -> None:
    """Считает баланс как сумму операций из transactions."""
    user = find_user(cur, email)
    if not user:
        print(f"Аккаунт {email} не найден.")
        sys.exit(1)

    cur.execute(
        """SELECT `amount`, `type`, `cost`, `balance_after`, `created_at`
           FROM `transactions` WHERE `user_id` = %s
           ORDER BY `created_at`, `id`""",
        (user["id"],),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"У аккаунта {email} нет транзакций — пересчитывать не из чего.")
        return

    total = 0.0
    for row in rows:
        amount = float(row["amount"] or 0)
        if str(row["type"]) in ("deposit", "refund"):
            total += amount
        else:
            total -= amount
        if row["cost"]:
            total -= float(row["cost"])

    last_balance = rows[-1]["balance_after"]
    print(f"Транзакций: {len(rows)}, сумма операций: {fmt_money(total)} ₽")
    print(f"Баланс в users: {fmt_money(user['balance'])} ₽, в последней транзакции: {fmt_money(last_balance)} ₽")

    current = float(user["balance"] or 0)
    if abs(current - total) < 0.01:
        print("Всё совпадает, править нечего.")
        return

    cur.execute("UPDATE `users` SET `balance` = %s WHERE `id` = %s", (total, user["id"]))
    print(f"Баланс исправлен: {fmt_money(current)} ₽ → {fmt_money(total)} ₽")


def main() -> int:
    args = sys.argv[1:]

    cnx = connect()
    try:
        cur = cnx.cursor(dictionary=True)
        try:
            if not args or args[0] == "list":
                list_users(cur)
                return 0

            command = args[0]
            if len(args) < 2:
                print("Укажи email: python balance_tool.py set 1@1.ru 1000")
                return 1
            email = args[1]

            if command == "set":
                if len(args) < 3:
                    print("Укажи сумму: python balance_tool.py set 1@1.ru 1000")
                    return 1
                set_balance(cur, email, float(args[2]), "Корректировка баланса (balance_tool)")
            elif command == "add":
                if len(args) < 3:
                    print("Укажи сумму: python balance_tool.py add 1@1.ru 500")
                    return 1
                user = find_user(cur, email)
                if not user:
                    print(f"Аккаунт {email} не найден.")
                    return 1
                new_balance = float(user["balance"] or 0) + float(args[2])
                set_balance(cur, email, new_balance, "Начисление (balance_tool)")
            elif command == "sync":
                sync_balance(cur, email)
            else:
                print(__doc__)
                return 1

            cnx.commit()
        finally:
            cur.close()
    finally:
        cnx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
