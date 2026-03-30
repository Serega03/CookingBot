import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.error import Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes

from config import BOT_TOKEN, SCHEDULE_HOUR, SCHEDULE_MINUTE, TIMEZONE
from recipes import get_daily_recipes, fetch_meal_by_category, format_recipe_message, create_session, MEAL_TYPES
from subscribers import add_subscriber, load_subscribers, remove_subscriber

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подписка на ежедневную рассылку рецептов."""
    chat_id = update.effective_chat.id
    if add_subscriber(chat_id):
        await update.message.reply_text(
            "Привет! 👋\n\n"
            "Я буду присылать тебе рецепты каждый день в 10:00 по Москве:\n"
            "🌅 Завтрак\n"
            "☀️ Обед\n"
            "🌙 Ужин\n\n"
            "Команды:\n"
            "/recipe — получить рецепт прямо сейчас\n"
            "/stop — отписаться от рассылки\n"
            "/help — помощь"
        )
    else:
        await update.message.reply_text(
            "Вы уже подписаны на рассылку рецептов! 🍳\n"
            "Рецепты приходят каждый день в 10:00 по Москве."
        )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отписка от рассылки."""
    chat_id = update.effective_chat.id
    if remove_subscriber(chat_id):
        await update.message.reply_text(
            "Вы отписались от рассылки рецептов. 😢\n"
            "Чтобы подписаться снова, отправьте /start"
        )
    else:
        await update.message.reply_text("Вы не были подписаны на рассылку.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Справка по командам бота."""
    await update.message.reply_text(
        "🍽 <b>CookingBot</b> — ежедневные рецепты\n\n"
        "Каждый день в 10:00 по Москве я присылаю 3 рецепта:\n"
        "🌅 Завтрак, ☀️ Обед, 🌙 Ужин\n\n"
        "<b>Команды:</b>\n"
        "/start — подписаться на рассылку\n"
        "/stop — отписаться\n"
        "/recipe — получить случайный рецепт сейчас\n"
        "/help — эта справка",
        parse_mode="HTML",
    )


async def recipe_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет один случайный рецепт прямо сейчас."""
    await update.message.reply_text("🔍 Ищу рецепт...")

    import random
    meal_type = random.choice(["breakfast", "lunch", "dinner"])
    categories = MEAL_TYPES[meal_type]["categories"]

    async with create_session() as session:
        meal = await fetch_meal_by_category(session, categories)

    if meal:
        text, image_url = format_recipe_message(meal, meal_type)
        if image_url:
            await update.message.reply_photo(photo=image_url)
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text("Не удалось загрузить рецепт. Попробуйте позже. 😔")


async def send_daily_recipes(bot) -> None:
    """Отправляет рецепты всем подписчикам (вызывается по расписанию)."""
    subscribers = load_subscribers()
    if not subscribers:
        logger.info("Нет подписчиков для рассылки.")
        return

    logger.info("Начинаю рассылку рецептов для %d подписчиков.", len(subscribers))

    async with create_session() as session:
        recipes = await get_daily_recipes(session)

    blocked_users = []

    for chat_id in subscribers:
        for text, image_url in recipes:
            try:
                if image_url:
                    await bot.send_photo(chat_id=chat_id, photo=image_url)
                await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML"
                )
            except Forbidden:
                logger.warning("Пользователь %d заблокировал бота.", chat_id)
                blocked_users.append(chat_id)
                break
            except Exception as e:
                logger.error("Ошибка отправки для %d: %s", chat_id, e)
                break

            await asyncio.sleep(0.05)

    # Удаляем заблокировавших пользователей
    for chat_id in blocked_users:
        remove_subscriber(chat_id)

    logger.info("Рассылка завершена. Заблокировали бота: %d.", len(blocked_users))


async def post_init(application: Application) -> None:
    """Запускает планировщик после старта event loop."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_recipes,
        CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, timezone=TIMEZONE),
        args=[application.bot],
        id="daily_recipes",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()

    logger.info(
        "Бот запущен. Рассылка каждый день в %02d:%02d по %s.",
        SCHEDULE_HOUR,
        SCHEDULE_MINUTE,
        TIMEZONE,
    )


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("recipe", recipe_now))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
