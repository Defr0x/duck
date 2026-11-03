"""Диагностика проекта: почему не работает сайт.

Запуск (из папки, где лежит app.py):
    python check.py

Скрипт ничего не меняет — только проверяет файлы, шаблоны, пакеты и базу
и в конце печатает список проблем.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

REQUIRED_FILES = [
    "app.py",
    "db.py",
    "llm.py",
    "requirements.txt",
    "templates/base.html",
    "templates/login.html",
    "templates/registration.html",
    "templates/profile.html",
    "templates/transactions.html",
    "static/style.css",
    "static/script.js",
]

problems = []
notes = []


def section(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 52 - len(title)))


def ok(text: str) -> None:
    print(f"  [ok]   {text}")


def warn(text: str) -> None:
    print(f"  [!]    {text}")
    notes.append(text)


def bad(text: str) -> None:
    print(f"  [ОШИБКА] {text}")
    problems.append(text)


def check_python() -> None:
    section("Python")
    print(f"  версия: {sys.version.split()[0]}")
    print(f"  папка:  {HERE}")


def check_files() -> None:
    section("Файлы проекта")
    for path in REQUIRED_FILES:
        if os.path.isfile(path):
            ok(path)
        else:
            bad(f"нет файла {path}")

    for folder in ("templates", "static"):
        if os.path.isdir(folder):
            extra = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
            print(f"  содержимое {folder}/: {', '.join(extra) or '— пусто —'}")
        else:
            bad(f"нет папки {folder}/ (она должна лежать рядом с app.py)")


def check_encodings() -> None:
    section("Кодировка файлов (должна быть UTF-8)")
    targets = []
    for root in (".", "templates", "static"):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name.endswith((".py", ".html", ".css", ".js")):
                targets.append(path)

    for path in targets:
        with open(path, "rb") as fh:
            raw = fh.read()
        if raw.startswith(b"\xef\xbb\xbf"):
            warn(f"{path}: сохранён с BOM (лучше «UTF-8 без BOM»)")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            bad(f"{path}: не UTF-8 (скорее всего сохранён в ANSI/cp1251) — пересохрани как UTF-8")
    if targets and not problems:
        ok(f"проверено файлов: {len(targets)}")


def check_templates() -> None:
    section("Шаблоны Jinja")
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        bad("не установлен jinja2 (обычно ставится вместе с Flask)")
        return

    if not os.path.isdir("templates"):
        return

    env = Environment(loader=FileSystemLoader("templates"))
    for name in ("base.html", "login.html", "registration.html", "profile.html", "transactions.html", "error.html"):
        if not os.path.isfile(os.path.join("templates", name)):
            if name == "error.html":
                warn("нет templates/error.html — вместо понятной ошибки будет стандартная страница Flask")
            else:
                bad(f"нет templates/{name}")
            continue
        try:
            env.get_template(name)
            ok(f"{name} разбирается без ошибок")
        except Exception as exc:
            bad(f"{name}: {type(exc).__name__}: {exc}")


def check_packages() -> None:
    section("Пакеты")
    for module, label, required in (
        ("flask", "flask", True),
        ("werkzeug", "werkzeug", True),
        ("mysql.connector", "mysql-connector-python", True),
        ("dotenv", "python-dotenv", False),
        ("llama_cpp", "llama-cpp-python (для чата)", False),
    ):
        try:
            __import__(module)
            ok(label)
        except ImportError:
            (bad if required else warn)(f"{label} не установлен")


def check_db() -> None:
    section("База данных MySQL")
    try:
        import db
    except ImportError as exc:
        if "mysql" in str(exc):
            bad("mysql-connector-python не установлен — поставь зависимости")
        else:
            bad(f"не удалось импортировать db.py: {exc}")
        return
    except Exception as exc:
        bad(f"db.py падает при импорте: {type(exc).__name__}: {exc}")
        return

    cfg = db.DB_CONFIG
    print(f"  host={cfg.get('host')}  database={cfg.get('database')}  user={cfg.get('user')}")

    try:
        cnx = db.connect()
    except Exception as exc:
        bad(f"не подключается к MySQL: {type(exc).__name__}: {exc}")
        notes.append("Проверь доступы в db.py и что хостинг разрешает внешние подключения к MySQL.")
        return

    try:
        cur = cnx.cursor(dictionary=True)
        try:
            cur.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cur.fetchall()]
            print(f"  таблицы в базе: {', '.join(tables) if tables else '— нет —'}")
            for table, columns in (
                ("users", ("id", "username", "email", "password_hash", "balance")),
                ("transactions", ("id", "user_id", "amount", "type", "cost", "description", "balance_after", "created_at")),
            ):
                if table not in tables:
                    bad(f"нет таблицы {table} (создастся сама при запуске app.py, если есть права CREATE)")
                    continue
                cur.execute(f"DESCRIBE `{table}`")
                have = {row["Field"] for row in cur.fetchall()}
                missing = [c for c in columns if c not in have]
                if missing:
                    bad(f"{table}: не хватает колонок {', '.join(missing)}")
                else:
                    ok(f"{table}: все нужные колонки на месте")
        finally:
            cur.close()
    finally:
        cnx.close()


def check_js() -> None:
    """Ловит синтаксические ошибки в static/script.js — из-за них молчит весь сайт."""
    section("JavaScript")
    path = "static/script.js"
    if not os.path.isfile(path):
        bad("нет static/script.js — тогда не работают формы, пополнение и чат")
        return

    import shutil
    import subprocess

    node = shutil.which("node")
    if node:
        try:
            result = subprocess.run(
                [node, "--check", path], capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                ok("script.js: синтаксис в порядке (проверено node)")
            else:
                first = (result.stderr or result.stdout).strip().splitlines()
                detail = " / ".join(first[:3]) if first else "ошибка разбора"
                bad(f"script.js: синтаксическая ошибка — {detail}")
        except Exception as exc:
            warn(f"не удалось прогнать node --check: {exc}")
    else:
        notes.append("node не установлен — JS проверен только по балансу скобок")

    # Простая эвристика на случай отсутствия node: считаем фигурные скобки
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"'(?:\\.|[^'\\\\])*'", "''", text)
    text = re.sub(r'"(?:\\.|[^"\\\\])*"', '""', text)
    text = re.sub(r"`(?:\\.|[^`\\\\])*`", "``", text)
    opens, closes = text.count("{"), text.count("}")
    if opens != closes:
        bad(f"script.js: несбалансированные фигурные скобки ({{ = {opens}, }} = {closes}) — "
            "скорее всего лишняя или пропущенная скобка")
    elif not node:
        ok("script.js: скобки сбалансированы")


def main() -> int:
    print("Диагностика проекта НейроЧат")
    check_python()
    check_files()
    check_encodings()
    check_templates()
    check_js()
    check_packages()
    check_db()

    section("Итог")
    if problems:
        print(f"  Найдено проблем: {len(problems)}")
        for item in problems:
            print(f"   • {item}")
    else:
        print("  Файлы, шаблоны и база в порядке — сайт должен запускаться.")

    if notes:
        print("\n  Замечания (не критично, но лучше поправить):")
        for item in dict.fromkeys(notes):
            print(f"   • {item}")

    print("\n  Если ошибка 500 осталась — скопируй traceback из терминала, где работает python app.py.")
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
