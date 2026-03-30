import asyncio
import json
import logging
import random

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.error import Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    BOT_TOKEN,
    PORT,
    RENDER_EXTERNAL_URL,
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    TIMEZONE,
)
from recipes import (
    MEAL_TYPES,
    create_session,
    fetch_meal_by_category,
    format_recipe_message,
    get_daily_recipes,
)
from subscribers import add_subscriber, load_subscribers, remove_subscriber

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─── Команды бота ───


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    chat_id = update.effective_chat.id
    if remove_subscriber(chat_id):
        await update.message.reply_text(
            "Вы отписались от рассылки рецептов. 😢\n"
            "Чтобы подписаться снова, отправьте /start"
        )
    else:
        await update.message.reply_text("Вы не были подписаны на рассылку.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    await update.message.reply_text("🔍 Ищу рецепт...")

    meal_type = random.choice(["breakfast", "lunch", "dinner"])
    categories = MEAL_TYPES[meal_type]["categories"]

    async with create_session() as session:
        meal = await fetch_meal_by_category(session, categories)

    if meal:
        text, image_url = await format_recipe_message(meal, meal_type)
        if image_url:
            await update.message.reply_photo(photo=image_url)
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(
            "Не удалось загрузить рецепт. Попробуйте позже. 😔"
        )


# ─── Рассылка по расписанию ───


async def send_daily_recipes(bot) -> None:
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

    for chat_id in blocked_users:
        remove_subscriber(chat_id)

    logger.info("Рассылка завершена. Заблокировали бота: %d.", len(blocked_users))


# ─── Запуск ───


async def post_init(application: Application) -> None:
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


async def run_render() -> None:
    """Запуск на Render.com: webhook + aiohttp-сервер с health-check."""
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recipe", recipe_now))

    # Инициализируем бота и ставим webhook
    await application.initialize()
    await application.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook",
                                      drop_pending_updates=True)
    await application.start()

    # Запускаем планировщик
    await post_init(application)

    # aiohttp-сервер: health-check + webhook
    async def health(request):
        return web.Response(text="OK")

    async def webhook_handler(request):
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")

    aiohttp_app = web.Application()
    aiohttp_app.router.add_get("/", health)
    aiohttp_app.router.add_post("/webhook", webhook_handler)

    runner = web.AppRunner(aiohttp_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logger.info("Render: сервер запущен на порту %d.", PORT)

    # Держим процесс живым
    try:
        await asyncio.Event().wait()
    finally:
        await application.stop()
        await application.shutdown()
        await runner.cleanup()


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recipe", recipe_now))

    if RENDER_EXTERNAL_URL:
        logger.info("Запуск в режиме webhook (Render).")
        asyncio.run(run_render())
    else:
        logger.info("Запуск в режиме polling (локально).")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
