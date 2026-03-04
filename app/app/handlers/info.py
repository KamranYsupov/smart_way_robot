import loguru
from aiogram import Router, F, html
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.services.telegram_user_service import TelegramUserService
from app.keyboards.donate import get_donate_keyboard
from app.core.config import settings
from app.services.matrix_service import MatrixService
from app.utils.sponsor import get_callback_value
from app.utils.pagination import Paginator
from app.utils.matrix import get_matrices_length
from app.utils.matrix import get_active_matrices, get_archived_matrices
from app.models.telegram_user import status_list, status_emoji_list
from app.db.commit_decorator import commit_and_close_session
from app.utils.texts import get_my_team_message, get_matrix_info_message
from app.models.telegram_user import MatrixBuildType
from app.models.telegram_user import TelegramUser

info_router = Router()


@info_router.message(F.text == "💡О Нас")
@inject
async def about_handler(
        message: Message,
) -> None:
    base_photo = FSInputFile("app/media/base_photo.jpg")

    presentation_keyboard = InlineKeyboardBuilder()
    presentation_button = InlineKeyboardButton(
        text="Презентация 📑",
        url=settings.presentation_link
    )
    chat_link_button = InlineKeyboardButton(
        text="💬 Чат LifeSol",
        url=settings.group_link
    )
    activation_guide_button = InlineKeyboardButton(
        text="Инструкция по активации",
        url=settings.activation_guide_link
    )
    presentation_keyboard.add(
        presentation_button,
        chat_link_button,
        activation_guide_button,
    )

    await message.answer_photo(
        photo=base_photo,
        reply_markup=presentation_keyboard.adjust(1).as_markup(),
    )


@info_router.callback_query(F.data.startswith("team_"))
@info_router.callback_query(F.data.startswith("archive_team_"))
@inject
async def team_inline_handler(
        callback: CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
        matrix_service: MatrixService = Provide[Container.matrix_service],
) -> None:
    callback_data_list = callback.data.split("_")
    is_archive = callback_data_list[0] == "archive"

    build_type_str = "b" # callback_data_list[-3] if is_archive else callback_data_list[-2]
    build_type = MatrixBuildType.BINARY \
        if build_type_str == "b" else MatrixBuildType.TRINARY


    current_user = await telegram_user_service.get_telegram_user(
        user_id=callback.from_user.id
    )
    matrices = await matrix_service.get_user_matrices(
        owner_id=current_user.id,
        build_type=build_type,
    )
    archived_matrices = get_archived_matrices(matrices, build_type)

    if is_archive:
        matrices = archived_matrices
        title_text = "АРХИВ УРОВНЕЙ:"
        page_number, previous_page_number = \
            map(int, callback.data.split("_")[-2:])
        callback_data_prefix = f"archive_team_{build_type_str}"
        back_button_data = f"team_{build_type_str}_{previous_page_number}"
    else:
        matrices = get_active_matrices(matrices, build_type)
        title_text = "АКТИВНЫЕ УРОВНИ:"
        page_number = int(callback.data.split("_")[-1])
        previous_page_number = None
        callback_data_prefix = f"team_{build_type_str}"
        back_button_data = f"donations_{build_type_str}"


    message, page_number, buttons, sizes = get_my_team_message(
        matrices=matrices,
        page_number=page_number,
        previous_page_number=previous_page_number,
        callback_data_prefix=callback_data_prefix
    )
    message = f"<b>{title_text}</b>\n\n" + message


    if not is_archive and archived_matrices:
        buttons["АРХИВ УРОВНЕЙ 🗄"] = f"archive_team_{build_type_str}_1_{page_number}"

    buttons["🔙 Назад"] = back_button_data

    await callback.message.edit_text(
        message,
        reply_markup=get_donate_keyboard(buttons=buttons, sizes=sizes),
        parse_mode="HTML",
    )


@info_router.callback_query(F.data.startswith("detail_matrix_"))
@inject
async def team_inline_handler(
        callback: CallbackQuery,
        matrix_service: MatrixService = Provide[Container.matrix_service],
) -> None:
    matrix_id = callback.data.split("_")[-1]
    matrix = await matrix_service.get_matrix(
        id=matrix_id
    )

    message_text = get_matrix_info_message(matrix)
    await callback.message.edit_text(text=message_text)



@info_router.message(F.text == "🔗 Реф ссылка")
async def referral_message_handler(message: Message):
    video = FSInputFile("app/media/lifesol.mp4")
    gift_network_keyboard = InlineKeyboardBuilder()
    registration_link = f"{settings.bot_link}?start={message.from_user.id}"
    registration_button = InlineKeyboardButton(
        text="🚀 РЕГИСТРАЦИЯ 🚀",
        url=registration_link
    )
    gift_network_keyboard.add(registration_button)
    await message.answer_video(
        video=video,
        caption=("💡Обучение по кошельку LifeSol, стейкинг 6-10% в месяц.\n\n"
                 "✅ Полностью DEX-продукт\n"
                 "✅ Прозрачный и проверяемый смарт-контракт\n"
                 "✅ Блокчейн Solana — скорость и минимальные комиссии сети\n"
                 "✅ Собственный токен с фиксированной эмиссией\n"
                 "✅ Надежная и удобная система хранения с сид-фразой\n"
                 "✅ Уникальная система стейкинга\n"
                 "✅ 10-уровневая партнерская программа\n"
                 "✅ Дополнительные промо и вознаграждения\n"
                 "✅ Международная ТОП-команда и сильные партнеры\n"
                 ),
        reply_markup=gift_network_keyboard.as_markup(),
    )
    await message.answer(
        f"Ваша реферальная ссылка: {registration_link}",
    )



@inject
async def referral_handler(
        current_user: TelegramUser,
        build_type: MatrixBuildType,
        page_number=1,
        per_page=20,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
        ],
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    invited_users = await telegram_user_service.get_invited_users(
        sponsor_user_id=current_user.user_id
    )
    default_buttons = {}

    if not invited_users:
        return "У вас пока нет реферралов.", None

    paginator = Paginator(
        invited_users,
        page_number=page_number,
        per_page=per_page
    )

    buttons = {}
    message_text = f"<b>Ваши рефералы (страница {page_number}):</b>\n\n"
    status_emoji_data = {
        status_list[i]: status_emoji_list[i]
        for i in range(len(status_list))
    }

    build_type_str = build_type.value[0]

    if paginator.has_previous():
        buttons |= {"◀ Пред.": f"referrals_{build_type_str}_{page_number - 1}"}
    if paginator.has_next():
        buttons |= {"След. ▶": f"referrals_{build_type_str}_{page_number + 1}"}

    if current_user.is_admin:
        buttons.update({
            "Отправить рассылку рефералам 📨": f"referral_message_0_{page_number}",
            "Отправить рассылку всем пользователям 👥📨": f"referral_message_1_{page_number}",
        })
    else:
        buttons.update({"Отправить рассылку 📨": f"referral_message_0_{page_number}"})

    if len(list(buttons.keys())) == 3:
        sizes = (2, 1, 1)
    else:
        sizes = (1, 1, 1)

    buttons.update(default_buttons)


    start_count = per_page * page_number - per_page + 1
    for user in paginator.get_page():
        user_status_emoji = status_emoji_data.get(user.get_status(build_type), "🆓",)
        message_text += f"{start_count}. @{user.username}: {user_status_emoji}\n"
        start_count += 1

    reply_markup = get_donate_keyboard(
        buttons=buttons,
        sizes=sizes
    )

    return message_text, reply_markup


@info_router.message(F.text == "⚙️ Настройки")
@info_router.callback_query(F.data.startswith("send_referrals_"))
@inject
async def send_referral_message_handler(
        aiogram_type: Message | CallbackQuery,
        telegram_user_service: TelegramUserService = Provide[
            Container.telegram_user_service
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

    current_user = await telegram_user_service.get_telegram_user(
        user_id=aiogram_type.from_user.id
    )
    if not current_user:
        return

    message_text, reply_markup = await referral_handler(
        current_user=current_user,
        build_type=build_type,
    )

    await telegram_method(
        text=message_text,
        reply_markup=reply_markup,
    )



