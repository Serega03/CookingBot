import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден. Создайте файл .env с токеном от @BotFather.")

BASE_DIR = Path(__file__).parent

# Render.com: автоматически устанавливает PORT и RENDER_EXTERNAL_URL
PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

TIMEZONE = "Europe/Moscow"
SCHEDULE_HOUR = 10
SCHEDULE_MINUTE = 0

SUBSCRIBERS_FILE = BASE_DIR / "subscribers.json"

MEALDB_BASE_URL = "https://www.themealdb.com/api/json/v1/1"

BREAKFAST_CATEGORIES = ["Breakfast"]
LUNCH_CATEGORIES = ["Pasta", "Chicken", "Vegetarian", "Seafood", "Starter"]
DINNER_CATEGORIES = ["Beef", "Lamb", "Pork", "Side", "Miscellaneous", "Goat", "Vegan"]

TELEGRAM_MSG_LIMIT = 4096
