from aiogram import html

from app.models.telegram_user import (
    DonateStatus,
    status_list,
    status_emoji_list,
    statuses_colors_data,
)
from app.models.telegram_user import TelegramUser
from app.models.matrix import Matrix
from app.utils.matrix import get_my_team_telegram_usernames, get_sorted_matrices
from app.utils.pagination import Paginator
from app.models.telegram_user import MatrixBuildType
from app.keyboards.donate import get_donate_value_with_currency

def get_donate_confirm_message(
        donate_sum: int,
        donate_status: DonateStatus,
        matrix_build_type: MatrixBuildType,
) -> str | None:
    if donate_status not in list(statuses_colors_data.keys()):
        return
    status = (
        f"{statuses_colors_data.get(donate_status)} - {donate_status.value.split()[0]}"
    )

    message_text = (
        f"✳️ Кто-то получил 🎁 {get_donate_value_with_currency(int(donate_sum), matrix_build_type)}\n\n"
        f"📶 Уровень: {status}\n\n"
        "💡SmartWay - качаем кошельки!"
    )

    return message_text


def get_user_statuses_statistic_message(
        users: list[TelegramUser],
        matrix_build_type: MatrixBuildType
) -> str:
    status_emoji_data = {
        status_list[i]: status_emoji_list[i]
        for i in range(len(status_list))
    }
    statuses_data = {"🆓": 0}
    statuses_data.update({status: 0 for status in status_emoji_list})

    for user in users:
        if user.get_status(matrix_build_type) == DonateStatus.NOT_ACTIVE:
            statuses_data["🆓"] += 1
            continue

        statuses_data[status_emoji_data[user.get_status(matrix_build_type)]] += 1

    message = ""

    for status, count in list(statuses_data.items())[::-1]:
        message += f"{status}: {count}\n"

    return message


def get_user_info_message(user: TelegramUser) -> str:
    message = (
        f"ID: {html.bold(user.id)}\n\n"
        f"Telegram ID: {html.bold(user.user_id)}\n"
        f"Username: @{user.username}\n"
        f"Полное имя: {html.bold(user.full_name)}\n"
        f"Дата и время регистрации: "
        + html.bold(user.created_at.strftime("%d.%m.%Y %H:%M"))
    )
    return message


def get_my_team_message(
        matrices: list[Matrix],
        page_number: int,
        per_page: int = 5,
        callback_data_prefix: str = "team",
        previous_page_number: int | None = None,

):
    message = ""
    sorted_matrices = get_sorted_matrices(matrices, status_list)
    paginator = Paginator(
        sorted_matrices,
        page_number=page_number,
        per_page=per_page
    )
    buttons = {}
    sizes = (1, 1)

    if len(paginator.get_page()):
        matrices = paginator.get_page()

        for matrix in matrices:
            message += get_matrix_info_message(matrix)
            message += "—————————\n\n" if matrix != matrices[-1] else ""
    else:
        message += "У вас нет активированных уровней"

    pagination_button_data = (
            f"{callback_data_prefix}_"
            + "{page_number}"
            + (f"_{previous_page_number}" if previous_page_number else "")
    )

    if paginator.has_previous():
        buttons |= {"◀ Пред.": pagination_button_data.format(page_number=page_number - 1)}
    if paginator.has_next():
        buttons |= {"След. ▶": pagination_button_data.format(page_number=page_number + 1)}

    if len(buttons) == 2:
        sizes = (2, 1)

    return message, page_number, buttons, sizes


def get_matrix_info_message(matrix: Matrix):
    message = (
        f"<b>Уровень {matrix.id.hex[0:5]}: {matrix.status.value}</b>\n\n"
    )

    first_level_usernames, second_level_usernames, length = \
        get_my_team_telegram_usernames(matrix)

    if not any(username != 0 for username in first_level_usernames) \
            and not any(username != 0 for username in second_level_usernames):
        message += "Все места свободны\n"
    else:
        message += f"<b>1 уровень:</b>\n"
        for index, telegram_username in enumerate(first_level_usernames):
            message += (
                    f"{index + 1}. "
                    + (f"@{telegram_username}" if telegram_username else "свободно")
                    + "\n"
            )

        message += f"\n<b>2 уровень:</b>\n"
        for index, telegram_username in enumerate(second_level_usernames):
            message += (
                    f"{index + 1}. "
                    + (f"@{telegram_username}" if telegram_username else "свободно")
                    + "\n"
            )

    message += f"\nВсего участников: <b>{length}</b>\n\n"

    return message





