import asyncio
import html
import logging
import random
import ssl

import aiohttp
import certifi

from config import (
    BREAKFAST_CATEGORIES,
    DINNER_CATEGORIES,
    LUNCH_CATEGORIES,
    MEALDB_BASE_URL,
    TELEGRAM_MSG_LIMIT,
)

logger = logging.getLogger(__name__)

MEAL_TYPES = {
    "breakfast": {
        "emoji": "🌅",
        "title": "Завтрак",
        "categories": BREAKFAST_CATEGORIES,
    },
    "lunch": {
        "emoji": "☀️",
        "title": "Обед",
        "categories": LUNCH_CATEGORIES,
    },
    "dinner": {
        "emoji": "🌙",
        "title": "Ужин",
        "categories": DINNER_CATEGORIES,
    },
}

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def create_session() -> aiohttp.ClientSession:
    """Создаёт aiohttp сессию с корректными SSL-сертификатами."""
    connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
    return aiohttp.ClientSession(connector=connector)


async def fetch_meal_by_category(
    session: aiohttp.ClientSession, categories: list[str]
) -> dict | None:
    """Получает случайное блюдо из одной из указанных категорий."""
    for attempt in range(3):
        try:
            category = random.choice(categories)
            url = f"{MEALDB_BASE_URL}/filter.php?c={category}"
            async with session.get(url) as resp:
                data = await resp.json()

            meals = data.get("meals")
            if not meals:
                continue

            meal = random.choice(meals)
            meal_id = meal["idMeal"]

            url = f"{MEALDB_BASE_URL}/lookup.php?i={meal_id}"
            async with session.get(url) as resp:
                data = await resp.json()

            meal_details = data.get("meals")
            if meal_details:
                return meal_details[0]

        except Exception as e:
            logger.warning("Попытка %d: ошибка загрузки рецепта: %s", attempt + 1, e)

    # Fallback: случайное блюдо
    try:
        url = f"{MEALDB_BASE_URL}/random.php"
        async with session.get(url) as resp:
            data = await resp.json()
        meals = data.get("meals")
        if meals:
            return meals[0]
    except Exception as e:
        logger.error("Не удалось загрузить даже случайный рецепт: %s", e)

    return None


def parse_ingredients(meal: dict) -> list[str]:
    """Собирает список ингредиентов из полей strIngredient/strMeasure."""
    ingredients = []
    for i in range(1, 21):
        ingredient = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if ingredient:
            if measure:
                ingredients.append(f"{measure} {ingredient}")
            else:
                ingredients.append(ingredient)
    return ingredients


def format_recipe_message(meal: dict, meal_type: str) -> tuple[str, str | None]:
    """Форматирует рецепт в HTML-сообщение для Telegram.

    Возвращает (text, image_url).
    """
    info = MEAL_TYPES[meal_type]
    emoji = info["emoji"]
    title = info["title"]

    name = html.escape(meal.get("strMeal", "Без названия"))
    instructions = (meal.get("strInstructions") or "Нет инструкций.").replace(
        "\r\n", "\n"
    )
    instructions = html.escape(instructions)
    image_url = meal.get("strMealThumb")

    ingredients = parse_ingredients(meal)
    ingredients_text = "\n".join(f"  • {html.escape(ing)}" for ing in ingredients)

    text = (
        f"{emoji} <b>{title}</b>\n\n"
        f"<b>{name}</b>\n\n"
        f"📝 <b>Ингредиенты:</b>\n{ingredients_text}\n\n"
        f"📖 <b>Приготовление:</b>\n{instructions}"
    )

    # Обрезаем если превышает лимит Telegram
    if len(text) > TELEGRAM_MSG_LIMIT:
        overhead = len(text) - len(instructions)
        max_instructions = TELEGRAM_MSG_LIMIT - overhead - 4  # для "...\n"
        # Обрезаем по последнему предложению
        truncated = instructions[:max_instructions]
        last_dot = truncated.rfind(".")
        if last_dot > 0:
            truncated = truncated[: last_dot + 1]
        truncated += "\n..."

        text = (
            f"{emoji} <b>{title}</b>\n\n"
            f"<b>{name}</b>\n\n"
            f"📝 <b>Ингредиенты:</b>\n{ingredients_text}\n\n"
            f"📖 <b>Приготовление:</b>\n{truncated}"
        )

    return text, image_url


async def get_daily_recipes(
    session: aiohttp.ClientSession,
) -> list[tuple[str, str | None]]:
    """Загружает 3 рецепта (завтрак, обед, ужин) параллельно."""
    tasks = []
    meal_type_keys = ["breakfast", "lunch", "dinner"]

    for key in meal_type_keys:
        categories = MEAL_TYPES[key]["categories"]
        tasks.append(fetch_meal_by_category(session, categories))

    meals = await asyncio.gather(*tasks)

    results = []
    for key, meal in zip(meal_type_keys, meals):
        if meal:
            text, image_url = format_recipe_message(meal, key)
            results.append((text, image_url))
        else:
            info = MEAL_TYPES[key]
            results.append(
                (f"{info['emoji']} <b>{info['title']}</b>\n\nНе удалось загрузить рецепт 😔", None)
            )

    return results
