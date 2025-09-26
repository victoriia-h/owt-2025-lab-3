import logging
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google import genai
from google.genai.errors import APIError # Додано для обробки специфічних помилок API

# === 1. КОНФІГУРАЦІЯ І ТОКЕНИ ===
# Отримуємо токени з системних змінних оточення (треба встановити у WebStorm)
# --- УВАГА: Для локального тестування ТИМЧАСОВО використовуємо ключі, надані в запиті.
#            Це НЕБЕЗПЕЧНО і має бути замінено на ос.getenv() для production!
TOKENTG = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not TOKENTG:
    # Загальне повідомлення для локального запуску
    raise ValueError(
        "TELEGRAM_BOT_TOKEN environment variable is required. "
        "Please set your Telegram bot token in your IDE or shell environment."
    )

# Налаштування логування (допомагає бачити, що відбувається)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ініціалізація Gemini
client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini клієнт ініціалізовано успішно.")
    except Exception as e:
        logger.error(f"Помилка ініціалізації Gemini: {e}")
        client = None
else:
    logger.warning("GEMINI_API_KEY не встановлено. Gemini функціональність буде обмежена.")

# Створення клавіатури меню
# Завдання: Студент (прізвище, група), IT-технології, Контакти, Prompt ChatGPT
reply_keyboard = [
    [KeyboardButton("👤 Студент")],
    [KeyboardButton("💻 IT-технології"), KeyboardButton("📞 Контакти")],
    [KeyboardButton("✍️ Чат з AI")] # Оновлена кнопка для переходу в режим чату
]
markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)


# === 2. ФУНКЦІЇ ОБРОБНИКІВ КОМАНД ===

# Обробка команди /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відправляє повідомлення при команді /start та показує меню."""
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    await update.message.reply_html(
        f"Привіт, {user.mention_html()}! Я твій лабораторний бот. Обери пункт меню або надрукуй `/chat` для запиту до Gemini.",
        reply_markup=markup,
    )

# Обробка команди /chat (починає режим чату з Gemini)
async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повідомляє користувача, що він може почати чат з Gemini."""
    if not update.message:
        return

    if context.user_data is not None:
        context.user_data['chat_mode'] = True # Встановлюємо режим чату
    await update.message.reply_text(
        "📝 **Режим Gemini активовано!** Надсилай свої запити. \n\n"
        "Щоб вийти з режиму, натисни кнопку меню або набери `/menu`.",
        parse_mode='Markdown'
    )

# Обробка команди /menu (повертає до основного меню)
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повертає до основного меню та вимикає режим чату."""
    if not update.message:
        return

    if context.user_data is not None:
        context.user_data['chat_mode'] = False # Вимикаємо режим чату
    await update.message.reply_text(
        "👋 Ти повернувся до головного меню.",
        reply_markup=markup
    )

# Обробка пунктів меню
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє натискання кнопок меню."""
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # 1. Студент
    if text == "👤 Студент":
        reply_text = (
            "**Студентські дані:**\n"
            "Прізвище: *Твоє Прізвище*\n"
            "Група: *Твоя Група*"
        )
    # 2. IT-технології
    elif text == "💻 IT-технології":
        reply_text = (
            "**IT-технології:**\n"
            "Створення чат-ботів, машинне навчання, web-розробка, кібербезпека. "
            "Я — приклад застосування **Python** та **Telegram API**."
        )
    # 3. Контакти
    elif text == "📞 Контакти":
        reply_text = (
            "**Контактна інформація:**\n"
            "Телефон: `+380 XXX XX XX XXX`\n"
            "E-mail: `твоя_пошта@example.com`"
        )
    # 4. Чат з AI (перехід у режим чату)
    elif text == "✍️ Чат з AI": # Перевірка оновленої назви кнопки
        await start_chat(update, context) # Перенаправляємо на функцію старту чату
        return
    else:
        # === МОДИФІКАЦІЯ: АВТОМАТИЧНА АКТИВАЦІЯ РЕЖИМУ ===
        # Якщо текст не є кнопкою меню, обробляємо як Gemini запит.

        is_chat_mode_active = context.user_data and context.user_data.get('chat_mode', False)

        if not is_chat_mode_active:
            if context.user_data is not None:
                context.user_data['chat_mode'] = True # Активація

            # Повідомляємо користувача про автоматичну активацію
            await update.message.reply_text(
                "✅ Автоматично активовано режим Gemini для твого запиту. \n"
                "Щоб вийти, набери `/menu` або скористайся кнопками.",
                parse_mode='Markdown'
            )

        await gemini_reply(update, context)
        return
        # =================================================

    await update.message.reply_text(reply_text, parse_mode='Markdown')


# Обробка запиту до Gemini
async def gemini_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відправляє повідомлення до Gemini API та повертає відповідь."""
    if not update.message or not update.effective_chat:
        return

    # Перевірка режиму чату
    if not context.user_data or not context.user_data.get('chat_mode'):
        # Надсилаємо лише коротке повідомлення, якщо режим все ще не активний
        logger.warning("gemini_reply викликано без активного chat_mode.")
        return

        # Показуємо користувачу, що бот обробляє запит
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    user_message = update.message.text

    try:
        if client:
            # Відправляємо запит до Gemini API
            # Додаємо системний промпт, щоб Gemini відповідав українською
            prompt = f"Ти корисний помічник, який відповідає українською мовою. Питання користувача: {user_message}"

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            reply = response.text or "Вибачте, не вдалося отримати відповідь від Gemini."
        else:
            # Якщо Gemini API недоступний, використовуємо заглушку
            reply = (
                f"🤖 Отримав твій запит: '{user_message}'\n\n"
                f"❗ Gemini API наразі недоступний. Будь ласка, перевір, чи встановлено "
                f"змінну оточення GEMINI_API_KEY та чи є підключення до мережі."
            )

    except APIError as e:
        # Обробка специфічних помилок API (наприклад, недійсний ключ)
        logger.error(f"Gemini API помилка: {e}")
        reply = "😔 Вибачте, сталася помилка при зверненні до Gemini API. Перевірте свій API-ключ."
    except Exception as e:
        logger.error(f"Невідома помилка при обробці Gemini запиту: {e}")
        reply = "😔 Вибачте, сталася непередбачена помилка. Спробуйте ще раз."

    await update.message.reply_text(reply)


# Обробник помилок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логує помилку та надсилає повідомлення користувачу."""
    logger.error('Update "%s" caused error "%s"', update, context.error)

    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "😔 Вибачте, сталася помилка. Спробуйте ще раз або зверніться до адміністратора."
        )


# === 3. НАЛАШТУВАННЯ ТА ЗАПУСК ===

def main() -> None:
    """Головна функція для налаштування та запуску бота."""
    # Створення об'єкта Application
    application = Application.builder().token(TOKENTG).build()

    # Додавання обробників
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chat", start_chat))
    application.add_handler(CommandHandler("menu", show_menu))

    # Обробник для текстових повідомлень (фільтрує команди)
    text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons)
    application.add_handler(text_handler)

    # Додаємо обробник помилок
    application.add_error_handler(error_handler)

    # Запуск бота
    logger.info("Бот запущено. Полінг...")
    # Додано drop_pending_updates=True для уникнення помилки 409 Conflict
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
