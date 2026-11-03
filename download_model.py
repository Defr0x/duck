"""Скачивает GGUF-модель заранее, чтобы первый чат не ждал загрузки.

Запуск:
    python download_model.py

Файл кладётся в ./models, путь к нему подхватывается автоматически
(или задай MODEL_PATH в окружении).
"""

import os
import sys

from llm import MODEL_FILE, MODEL_PATH, MODEL_REPO

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def main() -> int:
    target = MODEL_PATH or os.path.join(MODELS_DIR, MODEL_FILE)
    if os.path.exists(target):
        print(f"Модель уже есть: {target}")
        print(f"Запускай с MODEL_PATH={target} python app.py (или без переменной — найдётся сама)")
        return 0

    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    print(f"Скачиваю {MODEL_FILE} из {MODEL_REPO} …")
    print("Это ~400 МБ, займёт время в зависимости от скорости интернета.")

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("Нет модуля huggingface_hub. Установи: pip install huggingface_hub", file=sys.stderr)
        return 1

    try:
        path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            local_dir=os.path.join(MODELS_DIR),
        )
    except Exception as exc:
        print(f"Не удалось скачать модель: {exc}", file=sys.stderr)
        return 1

    print(f"Готово: {path}")
    print(f"Теперь: MODEL_PATH={path} python app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
