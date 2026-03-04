from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from app.models.telegram_user import TelegramUser, DonateStatus


def get_reply_keyboard(current_user: TelegramUser):
    keyboard = [
        [
            KeyboardButton(text="️⚡️ LifeSol инфо"),
            KeyboardButton(text="💡 SmartWay"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="🔗 Реф ссылка")
        ],
    ]

    reply_keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

    return reply_keyboard


reply_cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Отмена ❌")]
    ],
    resize_keyboard=True
)

