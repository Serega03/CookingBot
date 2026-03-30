import json
import logging
import os

from config import SUBSCRIBERS_FILE

logger = logging.getLogger(__name__)


def load_subscribers() -> set[int]:
    """Загружает множество chat_id подписчиков из JSON-файла."""
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            data = json.load(f)
        return set(data.get("subscribers", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_subscribers(subscribers: set[int]) -> None:
    """Атомарно сохраняет подписчиков в JSON-файл."""
    tmp_path = str(SUBSCRIBERS_FILE) + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump({"subscribers": sorted(subscribers)}, f, indent=2)
    os.replace(tmp_path, SUBSCRIBERS_FILE)


def add_subscriber(chat_id: int) -> bool:
    """Добавляет подписчика. Возвращает True если новый."""
    subs = load_subscribers()
    if chat_id in subs:
        return False
    subs.add(chat_id)
    save_subscribers(subs)
    logger.info("Новый подписчик: %d", chat_id)
    return True


def remove_subscriber(chat_id: int) -> bool:
    """Удаляет подписчика. Возвращает True если был подписан."""
    subs = load_subscribers()
    if chat_id not in subs:
        return False
    subs.discard(chat_id)
    save_subscribers(subs)
    logger.info("Подписчик отписался: %d", chat_id)
    return True
