import os
from datetime import datetime, timedelta
import uuid

import loguru
from aiogram import Router, F, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.schemas.donate import DonateEntity, DonateTransactionEntity
from app.services.donate_confirm_service import DonateConfirmService
from app.services.telegram_user_service import TelegramUserService
from app.models.telegram_user import status_list
from app.services.donate_service import DonateService
from app.schemas.telegram_user import TelegramUserEntity
from app.keyboards.donate import get_donate_keyboard
from app.utils.sponsor import get_callback_value
from app.models.telegram_user import DonateStatus, MatrixBuildType
from app.core.config import settings
from app.services.matrix_service import MatrixService
from app.schemas.matrix import MatrixEntity
from app.keyboards.donate import get_donations_keyboard, get_donate_value_with_currency
from app.db.commit_decorator import commit_and_close_session
from app.keyboards.reply import get_reply_keyboard
from app.utils.pagination import Paginator
from app.utils.sort import get_reversed_dict
from app.utils.sponsor import check_is_second_status_higher
from app.tasks.donate import check_is_donate_confirmed_or_delete_donate_task
from app.utils.texts import get_donate_confirm_message
from app.utils.excel import export_users_to_excel
from app.utils.texts import get_user_statuses_statistic_message
from app.tasks.matrix import check_is_matrix_free_with_donates_task

donate_router = Router()

@donate_router.callback_query(F.data.startswith("yes_"))
@inject
async def subscribe_handler(
        callback: CallbackQuery,
) -> None:
    sponsor_user_id = get_callback_value(callback.data)
    file_name = "app/media/registration_photo.jpg"
    file_input = FSInputFile(file_name)

    buttons = [
        InlineKeyboardButton(
            text="💬 ЧАТ 💬",
            url=settings.chat_link),
        InlineKeyboardButton(
            text="Проверить подписку ✅",
            callback_data=f"menu_{sponsor_user_id}",
        )
    ]
    keyboard = InlineKeyboardBuilder()
    keyboard.add(*buttons)

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=file_input,
        caption=f"🔑 Для доступа к основным функциям бота, подпишитесь на чат сообщества ⤵️",
        reply_markup=keyboard.adjust(1, 1).as_markup()
    )


@donate_router.callback_query(F.data.startswith("menu_"))
@inject
@commit_and_close_session
async def subscription_checker(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
):
    sponsor_user_id = get_callback_value(callback.data)
    sponsor = await telegram_user_service.get_telegram_user(user_id=sponsor_user_id)

    result = await callback.bot.get_chat_member(
        chat_id=settings.chat_id, user_id=callback.from_user.id
    )
    if result.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        await callback.answer("Ты не подписался ❌", show_alert=True)
        return

    await callback.message.delete()


    if not callback.from_user.username:
        await callback.message.answer(
            "Для регистрации добавьте пожалуйста <em>username</em> в свой telegram аккаунт",
            reply_markup=get_donate_keyboard(
                buttons={"Попробовать ещё раз": callback.data}
            )
        )
        return


    current_user = await telegram_user_service.get_telegram_user(
        user_id=callback.from_user.id
    )

    if not current_user:
        user_dict = callback.from_user.model_dump()
        user_id = user_dict.pop("id")

        user_dict["user_id"] = user_id
        user_dict["sponsor_user_id"] = sponsor_user_id
        user_dict["depth_level"] = sponsor.depth_level + 1
        user = TelegramUserEntity(**user_dict)

        current_user = await telegram_user_service.create_telegram_user(
            user=user,
            sponsor=sponsor,
        )

        try:
            await callback.bot.send_message(
                chat_id=sponsor.user_id,
                text=f"По вашей ссылке зарегистрировался пользователь @{current_user.username}."
            )
        except TelegramAPIError:
            pass

    await callback.message.answer(
        "✅ Готово! Выбери сервис", reply_markup=get_reply_keyboard(current_user)
    )

@donate_router.callback_query(F.data.startswith("donations_"))
@donate_router.message(F.text == "💡 SmartWay")
@inject
async def donations_menu_handler(
        aiogram_type: Message | CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    if isinstance(aiogram_type, Message):
        telegram_method = aiogram_type.answer
    else:
        callback = aiogram_type
        telegram_method = callback.message.edit_text

    build_type_str = "b"

    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY


    default_buttons = {
        "Транзакции 💳": f"{build_type_str}_transactions",
        "АКТИВНЫЕ УРОВНИ": f"team_{build_type_str}_1"
    }

    current_user = await telegram_user_service.get_telegram_user(
        user_id=aiogram_type.from_user.id
    )
    user_status = current_user.get_status(build_type)

    if current_user.is_admin:
        users = await telegram_user_service.get_list()
        bills_sum = await telegram_user_service.get_bills_sum(build_type=build_type)
        statuses_statistic_message = get_user_statuses_statistic_message(
            users,
            matrix_build_type=build_type
        )
        message_text = (
            f"Партнеров в SmartWay: <b>{len(users)}</b>\n"
            f"Всего подарили: <b>{get_donate_value_with_currency(int(bills_sum), build_type)}</b>\n\n"
            f"{statuses_statistic_message}\n"
            f"Лично приглашенных: <b>{current_user.invites_count}</b>\n"
            f"Получено подарков: "
            f"<b>{get_donate_value_with_currency(int(current_user.get_bill(build_type)), build_type)}</b>\n"
        )
        buttons = default_buttons
        admin_buttons = {
            "Скачать базу ⬇️": "excel_users",
            "Список забаненных пользователей 📇🅱️": "banned_users_1",
            "Забанить пользователя 🔒": "ban_user",
        }
        buttons.update(admin_buttons)

        await telegram_method(
            text=message_text,
            reply_markup=get_donate_keyboard(
                buttons=default_buttons,
            ),
        )
        return

    all_donates = await donate_confirm_service.get_donate_by_telegram_user_id(
        telegram_user_id=current_user.id,
        matrix_build_type=build_type,
    )
    buttons = {}
    if not all_donates:
        sponsor = await telegram_user_service.get_telegram_user(
            user_id=current_user.sponsor_user_id
        )
        buttons.update(get_reversed_dict(
            get_donations_keyboard(
                current_status=user_status,
                status_list=status_list,
                matrix_build_type=build_type,
            ))
        )
        message_text = (
                f"Ваш спонсор: "
                + ("@" + sponsor.username if sponsor.username else sponsor.first_name)
                + "\n"
                  f"Мой статус: <b>{user_status.value}</b>\n"
                  f"Лично приглашенных: <b>{current_user.invites_count}</b>\n"
                  f"Получено подарков: "
                  f"<b>{get_donate_value_with_currency(int(current_user.get_bill(build_type)), build_type)}</b>\n"
        )
    else:
        message_text = (
            "Возможность отправки следующего подарка будет "
            "доступна только после подтверждения текущего"
        )

    buttons.update(default_buttons)

    inline_buttons = [
        InlineKeyboardButton(text=button_text, callback_data=button_data)
        for button_text, button_data in buttons.items()
    ]
    inline_buttons.append(InlineKeyboardButton(
        text="Маркетинг",
        url=settings.marketing_button_link)
    )
    # inline_buttons.append(InlineKeyboardButton(
    #     text="Канал Подарков 🎁",
    #     url=settings.donates_channel_link
    # ))
    keyboard = InlineKeyboardBuilder()
    keyboard.add(*inline_buttons)

    await telegram_method(
        text=message_text,
        reply_markup=keyboard.adjust(1).as_markup(),
    )


@donate_router.callback_query(F.data == 'excel_users')
async def export_users_to_excel_callback_handler(
        callback: CallbackQuery,
):
    await callback.message.edit_text(
        "<em>Подождите немного ...</em>",
        parse_mode='HTML',
    )

    file_name = "app/telegram_users.xlsx"
    await export_users_to_excel(file_name)
    file_input = FSInputFile(file_name)

    await callback.message.delete()
    await callback.message.answer_document(file_input)

    os.remove(file_name)


@donate_router.callback_query(F.data.startswith("confirm_donate_"))
@inject
@commit_and_close_session
async def confirm_donate(
        callback: CallbackQuery,
) -> None:
    if "🔴" in callback.data.split("_"):
        return

    callback_donate_data = "_".join(callback.data.split("_")[1:])
    donate_sum = callback_donate_data.split("_")[-1]
    build_type_str = "b"
    matrix_build_type = MatrixBuildType.BINARY if build_type_str == "b" \
        else MatrixBuildType.TRINARY

    await callback.message.edit_text(
        text=f"Для завершения действия, "
             f"Вам необходимо отправить подарок {get_donate_value_with_currency(donate_sum, matrix_build_type)} "
             f"в течение {settings.donate_confirmation_time_minutes} минут. \n\n"
             "<b>Вы согласны продолжить?</b>",
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(
            buttons={
                "Да": callback_donate_data,
                "Нет": f"donations_{build_type_str}",
            },
            sizes=(2, 1),
        ),
    )

@donate_router.callback_query(F.data.startswith("donate_"))
@inject
@commit_and_close_session
async def donate_handler(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_service: DonateService = Provide[Container.donate_service],
        matrix_service: MatrixService = Provide[Container.matrix_service],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    build_type_str = "b"
    donate_sum = int(callback.data.split("_")[-1])

    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY

    status = donate_service.get_donate_status(donate_sum)
    current_user = await telegram_user_service.get_telegram_user(
        user_id=callback.from_user.id
    )

    if not callback.from_user.username:
        await callback.message.edit_text(
            "Перед отправкой подарка, "
            "добавьте пожалуйста <em>username</em> в свой телеграм аккаунт"
        )
        return

    if callback.from_user.username and current_user.username is None:
        current_user.username = callback.from_user.username

    all_donates = await donate_confirm_service.get_donate_by_telegram_user_id(
        telegram_user_id=current_user.id,
        matrix_build_type=build_type,
    )
    if all_donates:
        message_text = (
            "Возможность отправки следующего подарка будет "
            "доступна только после подтверждения текущего"
        )
        await callback.message.edit_text(
            text=message_text,
            reply_markup=get_donate_keyboard(buttons={"АКТИВНЫЕ УРОВНИ": "team_1"}),
        )
        return

    first_sponsor = await telegram_user_service.get_telegram_user(
        user_id=current_user.sponsor_user_id
    )

    donations_data = {}

    matrix, is_available = await donate_service.get_matrix_to_add_user(
        first_sponsor,
        current_user,
        donate_sum,
        status,
        donations_data,
        matrix_build_type=build_type,
    )
    now = datetime.now()

    if not is_available:
        await callback.message.edit_text(
            "Подождите пока подтвердятся подарки "
            "других пользователей на этот уровень."
        )
        check_is_matrix_free_with_donates_task.apply_async(
            eta=now + timedelta(
                minutes=settings.check_is_matrix_free_with_donates_minutes_interval
            ),
            kwargs={
                "chat_id": current_user.user_id,
                "matrix_id": matrix.id,
                "build_type_str": build_type_str,
                "donate_sum": donate_sum,
            },
        )
        return

    donate = await donate_confirm_service.create_donate(
        telegram_user_id=current_user.id,
        donate_data=donations_data,
        matrix_id=matrix.id,
        matrix_build_type=build_type,
        quantity=donate_sum,
    )


    check_is_donate_confirmed_or_delete_donate_task.apply_async(
        kwargs={
            "donate_id": donate.id,
            "donate_sender_user_id": current_user.user_id,
    },
        eta=now + timedelta(minutes=settings.donate_confirmation_time_minutes)
    )
    transactions = await donate_confirm_service.get_donate_transactions_by_donate_id(
        donate_id=donate.id
    )

    message = (
        f"Вы собираетесь отправить подарок в размере {get_donate_value_with_currency(donate_sum, build_type)}.\n\n"
        f"Для этого свяжитесь с пользователем, возьмите его реквизиты, "
        f"отправьте перевод и запросите подтверждение подарка:\n\n"
    )

    for transaction in transactions:
        sponsor = await telegram_user_service.get_telegram_user(
            id=transaction.sponsor_id
        )
        message += f"{get_donate_value_with_currency(int(transaction.quantity), build_type)} пользователю @{sponsor.username}\n"
        # блок отправки сообщений спонсорам
        try:
            await callback.bot.send_message(
                text=f"Вам подарок от @{current_user.username} "
                     f"в размере {get_donate_value_with_currency(int(transaction.quantity), build_type)}\n"
                     f"Нажмите \"Подтвердить подарок\" после получения подарка\n",
                chat_id=sponsor.user_id,
                reply_markup=get_donate_keyboard(
                    buttons={"Подтвердить подарок": f"first_{transaction.id}"}
                ),
            )
        except TelegramAPIError:
            pass

    await callback.message.delete()
    await callback.message.answer(message)


@donate_router.callback_query(F.data.startswith("first_"))
@inject
async def first_confirm_handler(
        callback: CallbackQuery,
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    transaction_id = get_callback_value(callback.data)
    transaction = await donate_confirm_service.get_donate_transaction_by_id(
        transaction_id
    )

    if transaction.is_canceled:
        await callback.message.edit_text(
            'Время подтверждения транзакции вышло.'
        )
        return

    await callback.message.edit_text(
        text="<b>Вы уверены?</b>",
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(
            buttons={
                "Да": f"confirm_transaction_{transaction_id}",
                "Нет": f"cancel_confirm_{transaction_id}",
            },
            sizes=(2, 1),
        ),
    )


@donate_router.callback_query(F.data.startswith("firstadmin_"))
@inject
async def first_admin_confirm_handler(
        callback: CallbackQuery,
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    transaction_id = callback.data.split("_")[-1]
    page_number = callback.data.split("_")[-2]
    build_type_str = callback.data.split("_")[-3]

    transaction = await donate_confirm_service.get_donate_transaction_by_id(
        transaction_id
    )

    if transaction.is_canceled:
        await callback.message.edit_text(
            'Время подтверждения транзакции вышло.',
            reply_markup=get_donate_keyboard(
                buttons={
                    "🔙 Назад ": f"all_transactions_{build_type_str}_{page_number}",
                },
                sizes=(1,),
            ),
        )
        return

    await callback.message.edit_text(
        text="<b>Вы уверены?</b>",
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(
            buttons={
                "Да": f"confirm_admin_{transaction_id}",
                "Нет": f"all_transactions_{build_type_str}_{page_number}",
            },
            sizes=(2, 1),
        ),
    )


@donate_router.callback_query(F.data.startswith("firsttran_"))
@inject
async def first_transactions_confirm_handler(
        callback: CallbackQuery,
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    transaction_id = callback.data.split("_")[-1]
    page_number = callback.data.split("_")[-2]
    build_type_str = callback.data.split("_")[-3]


    transaction = await donate_confirm_service.get_donate_transaction_by_id(
        transaction_id
    )

    if transaction.is_canceled:
        await callback.message.edit_text(
            'Время подтверждения транзакции вышло.',
            reply_markup=get_donate_keyboard(
                buttons={
                    "🔙 Назад ": f"transactions_to_me_{build_type_str}_{page_number}",
                },
                sizes=(1,),
            ),
        )
        return

    await callback.message.edit_text(
        text="<b>Вы уверены?</b>",
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(
            buttons={
                "Да": f"confirm_transaction_{transaction_id}",
                "Нет": f"transactions_to_me_{build_type_str}_{page_number}",
            },
            sizes=(2, 1),
        ),
    )


@donate_router.callback_query(F.data.startswith("cancel_confirm_"))
@inject
async def cancel_confirm(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
):
    transaction_id = uuid.UUID(get_callback_value(callback.data))
    transaction = await donate_confirm_service.get_donate_transaction_by_id(transaction_id)

    donate = await donate_confirm_service.get_donate_by_id(
        donate_id=transaction.donate_id
    )
    telegram_user = await telegram_user_service.get_telegram_user(
        id=donate.telegram_user_id
    )

    await callback.message.edit_text(
        text=f"Вам подарок от @{telegram_user.username} "
             f"в размере {get_donate_value_with_currency(int(transaction.quantity), donate.matrix_build_type)}\n"
             f'Нажмите "Подтвердить подарок" после получения подарка\n',
        reply_markup=get_donate_keyboard(
            buttons={"Подтвердить подарок": f"first_{transaction.id}"}
        ),
    )


@donate_router.callback_query(F.data.endswith("_transactions"))
@inject
async def get_transactions_menu(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
) -> None:
    build_type_str = callback.data.split("_")[0]

    buttons = {
        "Транзакции мне 📈": f"transactions_to_me_{build_type_str}_1",
        "Транзакции от меня 📉": f"transactions_from_me_{build_type_str}_1",
    }
    user_id = callback.from_user.id
    user = await telegram_user_service.get_telegram_user(user_id=user_id)
    if user.is_admin:
        buttons["Все транзакции 📊"] = f"all_transactions_{build_type_str}_1"

    buttons["🔙 Назад"] = f"donations_{build_type_str}"

    await callback.message.edit_text(
        "В этом разделе вы можете посмотреть информацию о подтверждении транзакций по подаркам.\n"
        "Выберете раздел:",
        reply_markup=get_donate_keyboard(buttons=buttons),
    )


@donate_router.callback_query(F.data.startswith("transactions_to_me_"))
@inject
@commit_and_close_session
async def get_transactions_list_to_me(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    page_number = int(callback.data.split("_")[-1])
    build_type_str = "b"
    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY

    user_id = callback.from_user.id
    user = await telegram_user_service.get_telegram_user(user_id=user_id)
    transactions = await (donate_confirm_service
    .get_donate_transaction_by_sponsor_id_and_matrix_build_type(
        sponsor_id=user.id,
        matrix_build_type=build_type,
    ))

    paginator = Paginator(transactions, page_number=page_number, per_page=5)
    buttons = {}
    sizes = (1, 1)

    if paginator.has_previous():
        buttons |= {"◀ Пред.": f"transactions_to_me_{build_type_str}_{page_number - 1}"}
    if paginator.has_next():
        buttons |= {"След. ▶": f"transactions_to_me_{build_type_str}_{page_number + 1}"}

    if len(buttons) == 2:
        sizes = (2, 1)

    message = "Транзакции от пользователей Вам.\n\n"
    transactions = paginator.get_page()

    if transactions:
        for transaction in transactions:
            donate = await donate_confirm_service.get_donate_by_id(
                donate_id=transaction.donate_id
            )
            user = await telegram_user_service.get_telegram_user(
                id=donate.telegram_user_id
            )
            message += (
                f"ID: {transaction.id}\n"
                f"Сумма: {get_donate_value_with_currency(int(transaction.quantity), donate.matrix_build_type)}\n"
                f"От: @{user.username}\n"
                f"Дата: {transaction.created_at}\n"
            )
            message += "<b>ОТМЕНЕНА ❌</b>\n" if transaction.is_canceled else ''
            message += (
                "Подтверждена: " +
                ("Да" if transaction.is_confirmed else "<b>Нет</b>") +
                "\n\n"
            )
            if not transaction.is_confirmed and not transaction.is_canceled:
                buttons[f"Подтвердить {transaction.id}"] = (
                    f"firsttran_{build_type_str}_{page_number}_{transaction.id}"
                )
    else:
        message = "У вас нет транзакций"

    buttons["🔙 Назад"] = f"{build_type_str}_transactions"
    await callback.message.edit_text(
        message,
        reply_markup=get_donate_keyboard(
            buttons=buttons,
            sizes=sizes,
        ),
    )


@donate_router.callback_query(F.data.startswith("transactions_from_me_"))
@inject
async def get_transactions_list_from_me(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_service: DonateService = Provide[Container.donate_service],
        matrix_service: MatrixService = Provide[Container.matrix_service],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    page_number = int(callback.data.split("_")[-1])
    build_type_str = "b"
    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY

    user_id = callback.from_user.id
    user = await telegram_user_service.get_telegram_user(user_id=user_id)
    donates = await donate_confirm_service.get_all_my_donates_and_transactions(
        telegram_user_id=user.id,
        matrix_build_type=build_type,
    )

    paginator = Paginator(list(donates.items()), page_number=page_number, per_page=3)
    buttons = {}
    sizes = (1, 1)
    message = "<b><u>Ваши подарки и транзакции</u></b>\n\n"

    donates = paginator.get_page()
    if donates:
        for donate, transactions in donates:
            message += (
                f"<b><u>Подарок на сумму: "
                f"{get_donate_value_with_currency(int(donate.quantity), donate.matrix_build_type)}</u></b>\n"
                f"ID: {donate.id}\n"
                f"Дата: {donate.created_at}\n"
            )
            message += "<b>ОТМЕНЕН ❌</b>\n" if donate.is_canceled else ''
            message += (
                "Подтвержден: " +
                ("Да" if donate.is_confirmed else "<b>Нет</b>") +
                "\n\n"
            )

            if transactions:
                for transaction in transactions:
                    sponsor = await telegram_user_service.get_telegram_user(
                        id=transaction.sponsor_id
                    )
                    message += f"Кому: @{sponsor.username}\n\n"
    else:
        message = "У Вас нет подарков"

    if paginator.has_previous():
        buttons |= {"◀ Пред.": f"transactions_from_me_{build_type_str}_{page_number - 1}"}
    if paginator.has_next():
        buttons |= {"След. ▶": f"transactions_from_me_{build_type_str}_{page_number + 1}"}

    if len(buttons) == 2:
        sizes = (2, 1)

    buttons["🔙 Назад"] = f"{build_type_str}_transactions"

    await callback.message.edit_text(
        message,
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(buttons=buttons, sizes=sizes),
    )


@donate_router.callback_query(F.data.startswith("all_transactions_"))
@inject
async def get_all_transactions(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    page_number = int(callback.data.split("_")[-1])
    build_type_str = "b"
    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY

    donates_and_transactions = (
        await donate_confirm_service.get_all_donates_and_transactions(
            matrix_build_type=build_type,
        )
    )

    paginator = Paginator(
        list(donates_and_transactions.items()), page_number=page_number, per_page=3
    )
    buttons = {}
    sizes = (1, 1)
    message = "Все подарки и транзакции\n\n"
    donates_and_transactions = paginator.get_page()

    if paginator.has_previous():
        buttons |= {"◀ Пред.": f"all_transactions_{build_type_str}_{page_number - 1}"}
    if paginator.has_next():
        buttons |= {"След. ▶": f"all_transactions_{build_type_str}_{page_number + 1}"}

    if len(buttons) == 2:
        sizes = (2, 1)

    if donates_and_transactions:
        for donate, transactions in paginator.get_page():
            user = await telegram_user_service.get_telegram_user(
                id=donate.telegram_user_id
            )
            message += (
                f"<b><u>Подарок на сумму: "
                f"{get_donate_value_with_currency(int(donate.quantity), donate.matrix_build_type)}</u></b>\n"
                f"ID: {donate.id}\n"
                f"Дата: {donate.created_at}\n"
            )
            message += "<b>ОТМЕНЕН ❌</b>\n\n" if donate.is_canceled else ''
            message += "Транзакции по подарку: \n\n"
            if transactions:
                for transaction in transactions:
                    sponsor = await telegram_user_service.get_telegram_user(
                        id=transaction.sponsor_id
                    )
                    message += (
                        f"ID: {transaction.id}\n"
                        f"Сумма: {get_donate_value_with_currency(int(transaction.quantity), donate.matrix_build_type)}\n"
                        f"От кого: @{user.username}\n"
                        f"Кому: @{sponsor.username}\n"
                    )
                    message += (
                        "Подтверждена: " +
                        ("Да" if transaction.is_confirmed else "<b>Нет</b>") +
                        "\n\n"
                    )
                    if not transaction.is_confirmed and not transaction.is_canceled:
                        buttons[f"Подтвердить {transaction.id}"] = (
                            f"firstadmin_{build_type_str}_{page_number}_{transaction.id}"
                        )

    buttons["🔙 Назад"] = f"{build_type_str}_transactions"
    await callback.message.edit_text(
        message,
        parse_mode="HTML",
        reply_markup=get_donate_keyboard(
            buttons=buttons,
            sizes=sizes,
        ),
    )


@donate_router.callback_query(F.data.startswith("confirm_transaction_"))
@inject
@commit_and_close_session
async def confirm_transaction(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        matrix_service: MatrixService = Provide[Container.matrix_service],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    transaction_id = uuid.UUID(get_callback_value(callback.data))

    transaction = await donate_confirm_service.get_donate_transaction_by_id(transaction_id)

    donate = await donate_confirm_service.get_donate_by_id(
        donate_id=transaction.donate_id
    )
    if donate.is_confirmed:
        await callback.message.edit_text("Транзакция уже подтверждена")
        return

    transaction = await donate_confirm_service.set_donate_transaction_is_confirmed(
        donate_transaction_id=transaction_id
    )
    sponsor = await telegram_user_service.get_telegram_user(id=transaction.sponsor_id)
    sponsor.add_to_bill(
        value=transaction.quantity,
        matrix_build_type=donate.matrix_build_type,
    )

    sender_user = await telegram_user_service.get_telegram_user(
        id=donate.telegram_user_id
    )
    donate_confirm = await donate_confirm_service.check_donate_is_confirmed(
        donate_id=transaction.donate_id
    )

    if donate_confirm:
        current_matrix_id = donate.matrix_id
        current_matrix = await matrix_service.get_matrix(id=current_matrix_id)

        sender_matrix_dict = {
            "owner_id": sender_user.id,
            "status": current_matrix.status,
            "build_type": donate.matrix_build_type,
        }
        sender_matrix_entity = MatrixEntity(**sender_matrix_dict)
        sender_matrix = await matrix_service.create_matrix(matrix=sender_matrix_entity)

        await matrix_service.add_to_matrix(current_matrix, sender_matrix, sender_user)

        if check_is_second_status_higher(
            sender_user.get_status(donate.matrix_build_type),
            current_matrix.status
        ):
            sender_user.set_status(
                status=current_matrix.status,
                matrix_build_type=donate.matrix_build_type,
            )

        try:
            await callback.bot.send_message(
                text=f"Ваш подарок успешно подтвержден!\n",
                chat_id=sender_user.user_id,
                reply_markup=get_reply_keyboard(sender_user),
            )
        except TelegramAPIError:
            pass

        try:
            channel_donate_confirm_text = get_donate_confirm_message(
                donate_sum=donate.quantity,
                donate_status=current_matrix.status,
                matrix_build_type=donate.matrix_build_type,
            )
            await callback.bot.send_message(
                text=channel_donate_confirm_text,
                chat_id=settings.donates_channel_id,
            )
        except TelegramAPIError:
            pass


    message = ("Транзакция на сумму "
               f"{get_donate_value_with_currency(int(transaction.quantity), donate.matrix_build_type)} "
               f"от пользователя @{sender_user.username} подтверждена.")
    await callback.message.edit_text(
        message, reply_markup=get_donate_keyboard(
            buttons={"🔙 Назад": f"{donate.matrix_build_type.value[0]}_transactions"}
        )
    )


@donate_router.callback_query(F.data.startswith("confirm_admin_"))
@inject
@commit_and_close_session
async def confirm_admin_transaction(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        matrix_service: MatrixService = Provide[Container.matrix_service],
        donate_confirm_service: DonateConfirmService = Provide[
            Container.donate_confirm_service
        ],
) -> None:
    transaction_id = uuid.UUID(callback.data.split("_")[-1])
    transaction = await donate_confirm_service.get_donate_transaction_by_id(transaction_id)

    donate = await donate_confirm_service.get_donate_by_id(
        donate_id=transaction.donate_id
    )
    if donate.is_confirmed:
        await callback.message.edit_text("Транзакция уже подтверждена")
        return

    transaction = await donate_confirm_service.set_donate_transaction_is_confirmed(
        donate_transaction_id=transaction_id
    )
    sponsor = await telegram_user_service.get_telegram_user(id=transaction.sponsor_id)
    sponsor.add_to_bill(
        value=transaction.quantity,
        matrix_build_type=donate.matrix_build_type,
    )
    try:
        if not sponsor.is_admin:
            await callback.bot.send_message(
                text=f"<strong>Транзакция <em>{transaction_id}</em> подтверждена админом</strong>",
                chat_id=sponsor.user_id,
                parse_mode="HTML",
                reply_markup=get_reply_keyboard(sponsor),
            )
    except TelegramAPIError:
        pass

    sender_user = await telegram_user_service.get_telegram_user(
        id=donate.telegram_user_id
    )
    donate_confirm = await donate_confirm_service.check_donate_is_confirmed(
        donate_id=transaction.donate_id
    )

    if donate_confirm:
        current_matrix_id = donate.matrix_id
        current_matrix = await matrix_service.get_matrix(id=current_matrix_id)

        sender_matrix_dict = {
            "owner_id": sender_user.id,
            "status": current_matrix.status,
            "build_type": donate.matrix_build_type,
        }
        sender_matrix_entity = MatrixEntity(**sender_matrix_dict)
        sender_matrix = await matrix_service.create_matrix(matrix=sender_matrix_entity)

        await matrix_service.add_to_matrix(current_matrix, sender_matrix, sender_user)

        if check_is_second_status_higher(
            sender_user.get_status(donate.matrix_build_type),
            current_matrix.status
        ):
            sender_user.set_status(
                status=current_matrix.status,
                matrix_build_type=donate.matrix_build_type,
            )

        try:
            await callback.bot.send_message(
                text=f"Ваш подарок успешно подтвержден!\n",
                chat_id=sender_user.user_id,
                reply_markup=get_reply_keyboard(sender_user),
            )
        except TelegramAPIError:
            pass
        try:
            channel_donate_confirm_text = get_donate_confirm_message(
                donate_sum=donate.quantity,
                donate_status=current_matrix.status,
                matrix_build_type=donate.matrix_build_type,
            )
            await callback.bot.send_message(
                text=channel_donate_confirm_text,
                chat_id=settings.donates_channel_id,
            )
        except TelegramAPIError:
            pass

    message = (f"Транзакция на сумму "
               f"{get_donate_value_with_currency(int(transaction.quantity), donate.matrix_build_type)} "
               f"от пользователя @{sender_user.username} подтверждена.")
    await callback.message.edit_text(
        message, reply_markup=get_donate_keyboard(
            buttons={"🔙 Назад": f"{donate.matrix_build_type.value[0]}_transactions"}
        )
    )
