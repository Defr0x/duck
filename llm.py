"""Локальная нейросеть: llama-cpp-python + Qwen2.5-0.5B-Instruct (GGUF).

Модель грузится один раз и висит в памяти процесса. Если llama-cpp-python
не установлен или файл модели не найден — сайт продолжает работать, а чат
честно сообщает, чего не хватает (вместо падения при импорте, как в примере).

Переменные окружения (все необязательные):
    MODEL_PATH  — путь к локальному .gguf (если задан — скачивание не нужно)
    MODEL_REPO  — репозиторий на Hugging Face
    MODEL_FILE  — имя файла в репозитории
    DEMO_MODE=1 — не грузить модель вовсе (демо-режим без нейросети)
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

MODEL_REPO = os.environ.get("MODEL_REPO", "bartowski/Qwen2.5-0.5B-Instruct-GGUF")
MODEL_FILE = os.environ.get("MODEL_FILE", "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf")
MODEL_PATH = os.environ.get("MODEL_PATH", "").strip()
DEMO_MODE = os.environ.get("DEMO_MODE") == "1"

SYSTEM_PROMPT = "Ты полезный ассистент. Отвечай кратко и по-русски."

HINT = (
    "Чтобы включить нейросеть: установи llama-cpp-python "
    "(pip install llama-cpp-python) и запусти python download_model.py."
)


def demo_reply(message: str) -> str:
    """Ответ в демо-режиме: интерфейс чата живой, модели нет."""
    return (
        "Это демо-режим без нейросети — модель тут не загружена.\n"
        "На сервере с llama-cpp-python и скачанным .gguf здесь будет настоящий ответ.\n\n"
        f"Твоё сообщение я получил: «{message[:200]}»"
    )


class ModelUnavailable(RuntimeError):
    """Модель не загружена — текст ошибки показываем пользователю."""


def build_prompt(messages) -> str:
    """Собирает промпт в формате ChatML — том же, что использует Qwen."""
    parts = [f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"]
    for msg in messages:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        parts.append(f"<|im_start|>{role}\n{msg.get('content', '')}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


class LocalModel:
    def __init__(self) -> None:
        self._llm = None
        self._error = None
        self._loading = False
        self._load_lock = threading.Lock()   # загрузка модели — один раз
        self._chat_lock = threading.Lock()   # генерация — по одному запросу

    # ---------- состояние ----------

    @property
    def ready(self) -> bool:
        return self._llm is not None

    @property
    def loading(self) -> bool:
        return self._loading

    def status(self) -> dict:
        return {
            "ready": self.ready,
            "loading": self.loading,
            "error": self._error,
            "model": MODEL_FILE,
            "repo": MODEL_REPO,
        }

    # ---------- загрузка ----------

    def load(self) -> None:
        """Загружает модель (повторные вызовы бесплатны)."""
        if self._llm is not None or self._error is not None:
            return
        with self._load_lock:
            if self._llm is not None or self._error is not None:
                return
            self._loading = True
            try:
                if DEMO_MODE:
                    raise ModelUnavailable("Демо-режим: нейросеть отключена.")
                try:
                    from llama_cpp import Llama
                except ImportError:
                    raise ModelUnavailable("Не установлен llama-cpp-python.") from None

                if MODEL_PATH:
                    if not os.path.exists(MODEL_PATH):
                        raise ModelUnavailable(f"Файл модели не найден: {MODEL_PATH}")
                    logger.info("Загружаю модель из файла %s", MODEL_PATH)
                    self._llm = Llama(model_path=MODEL_PATH, n_ctx=2048, verbose=False)
                else:
                    logger.info("Загружаю модель %s из %s (первый запуск — скачивание)", MODEL_FILE, MODEL_REPO)
                    self._llm = Llama.from_pretrained(
                        repo_id=MODEL_REPO,
                        filename=MODEL_FILE,
                        n_ctx=2048,
                        verbose=False,
                    )
                logger.info("Модель загружена.")
            except ModelUnavailable as exc:
                self._error = str(exc)
                logger.warning("Нейросеть недоступна: %s", exc)
            except Exception as exc:  # сеть, память, битый файл и т.п.
                self._error = f"Не удалось загрузить модель: {exc}"
                logger.exception("Ошибка загрузки модели")
            finally:
                self._loading = False

    def warmup_async(self) -> None:
        """Грузит модель в фоне, чтобы сайт открывался сразу."""
        if self._llm is not None or self._error is not None or self._loading:
            return
        threading.Thread(target=self.load, name="model-warmup", daemon=True).start()

    # ---------- генерация ----------

    def generate(self, messages, max_tokens: int = 300, temperature: float = 0.7) -> str:
        self.load()
        if self._llm is None:
            raise ModelUnavailable(self._error or "Модель не загружена.")

        prompt = build_prompt(messages)
        with self._chat_lock:
            output = self._llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.9,
                repeat_penalty=1.1,
                stop=["<|im_end|>", "<|im_start|>"],
            )
        reply = output["choices"][0]["text"].strip()
        return reply or "Не смог сформулировать ответ, попробуй переспросить."


model = LocalModel()
