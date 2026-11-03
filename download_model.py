"""Скачивает GGUF-модель заранее, чтобы первый чат не ждал загрузки.

Запуск (из папки проекта):
    python download_model.py

Файл кладётся в папку models/ рядом с app.py и подхватывается сам —
после скачивания достаточно запустить python app.py.
"""

import os
import sys

from llm import MODEL_FILE, MODEL_REPO, MODELS_DIR, resolve_model_path


def main() -> int:
    existing = resolve_model_path()
    if existing:
        print(f"Модель уже на месте: {existing}")
        print("Просто запусти: python app.py")
        return 0

    target = os.path.join(MODELS_DIR, MODEL_FILE)
    os.makedirs(MODELS_DIR, exist_ok=True)

    print(f"Скачиваю {MODEL_FILE} из {MODEL_REPO} …")
    print("Это ~400 МБ, займёт время в зависимости от скорости интернета.")

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("Нет модуля huggingface_hub. Установи: pip install huggingface_hub", file=sys.stderr)
        return 1

    try:
        path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE, local_dir=MODELS_DIR)
    except Exception as exc:
        print(f"Не удалось скачать модель: {exc}", file=sys.stderr)
        print("Проверь интернет и доступ к huggingface.co, затем повтори запуск.", file=sys.stderr)
        return 1

    print(f"\nГотово: {path}")
    print("Теперь запускай python app.py — модель найдётся сама.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
