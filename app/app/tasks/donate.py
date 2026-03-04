import asyncio
import uuid
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from celery import shared_task

from app.core.container import Container
from app.db.commit_decorator import commit_and_close_session
from app.models.donate import Donate
from app.models.telegram_user import TelegramUser
from app.services.donate_confirm_service import DonateConfirmService
from app.services.telegram_user_service import TelegramUserService
from app.core import celery_app
from app.loader import bot
from app.tasks.const import (
    loop
)


@commit_and_close_session
async def check_is_donate_confirmed_or_delete_donate(
        donate_id: str | uuid.UUID,
        donate_sender_user_id: Optional[int],
):
    container = Container()
    donate_confirm_service = container.donate_confirm_service()
    telegram_user_service = container.telegram_user_service()
    is_confirmed: bool = await donate_confirm_service.check_donate_is_confirmed(donate_id=donate_id)

    if is_confirmed:
        return

    if not donate_sender_user_id:
        donate: Donate = await donate_confirm_service.get_donate_by_id(donate_id)
        telegram_user: TelegramUser = await telegram_user_service.get_telegram_user(id=donate.telegram_user_id)
        donate_sender_user_id = telegram_user.user_id

    await donate_confirm_service.cancel_donate_with_transactions(donate_id=donate_id)

    try:
        await bot.send_message(
            chat_id=donate_sender_user_id,
            text="Время отправки подарка вышло."
        )
    except TelegramAPIError:
        pass


@celery_app.task
def check_is_donate_confirmed_or_delete_donate_task(
        donate_id: str | uuid.UUID,
        donate_sender_user_id: Optional[int],
):
    return loop.run_until_complete(check_is_donate_confirmed_or_delete_donate(
        donate_id=donate_id,
        donate_sender_user_id=donate_sender_user_id,
    ))
