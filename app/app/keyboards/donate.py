import loguru
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from app.models.telegram_user import DonateStatus, MatrixBuildType, TelegramUser


def get_donate_keyboard(*, buttons: dict[str, str], sizes: tuple = (1, 1)):
    keyboard = InlineKeyboardBuilder()

    for text, data in buttons.items():
        keyboard.add(InlineKeyboardButton(text=text, callback_data=data))

    return keyboard.adjust(*sizes).as_markup()


def get_donate_value_with_currency(donate_sum: int, matrix_build_type: MatrixBuildType) -> str:
    return f"${donate_sum}"


def get_donations_keyboard(
        current_status: DonateStatus,
        status_list: list[DonateStatus],
        matrix_build_type: MatrixBuildType,
) -> dict:
    #build_type_str = "t" if matrix_build_type == MatrixBuildType.TRINARY else "b"
    build_type_str = "b"

    buttons = {}
    if current_status.value == DonateStatus.NOT_ACTIVE.value:
        first_status = status_list[0]
        first_donate_sum = first_status.get_status_donate_value(matrix_build_type)
        first_button_text = (
            f"🟢{first_status.value} - {get_donate_value_with_currency(first_donate_sum, matrix_build_type)}🟢"
        )

        buttons[first_button_text] = f"confirm_donate_🟢_{build_type_str}_{first_donate_sum}"
        for status in status_list[1:]:
            donate_sum = status.get_status_donate_value(matrix_build_type)
            button_text = \
                f"🔴{status.value} - {get_donate_value_with_currency(donate_sum, matrix_build_type)}🔴"
            buttons[button_text] = \
                f"confirm_donate_🔴_{build_type_str}_{donate_sum}"


        return buttons

    if current_status.value == DonateStatus.GOLD.value:
        for status in status_list:
            donate_sum = status.get_status_donate_value(matrix_build_type)
            button_text = \
                f"🟢{status.value} - {get_donate_value_with_currency(donate_sum, matrix_build_type)}🟢"
            buttons[button_text] = \
                f"confirm_donate_🟢_{build_type_str}_{donate_sum}"

        return buttons

    count = 0
    for status in status_list:
        if current_status.value == status.value:
            for i in status_list[: status_list.index(status)]:
                button_text = (
                    f"🟢{i.value} - "
                    f"{get_donate_value_with_currency(i.get_status_donate_value(matrix_build_type), matrix_build_type)}🟢"
                )
                buttons[button_text] = \
                    f"confirm_donate_🟢_{build_type_str}_{i.get_status_donate_value(matrix_build_type)}"
                count += 1

            button_text = (
                f"🔴{status.value} - "
                f"{get_donate_value_with_currency(status.get_status_donate_value(matrix_build_type), matrix_build_type)}🔴"
            )
            buttons[button_text] = \
                f"confirm_donate_🔴_{build_type_str}_{status.get_status_donate_value(matrix_build_type)}"

            buttons[(
                f"🟢{status_list[count + 1].value} - "
                f"{get_donate_value_with_currency(status_list[count + 1].get_status_donate_value(matrix_build_type), matrix_build_type)}🟢"
            )] = (
                f"confirm_donate_🟢_{build_type_str}_"
                f"{status_list[count + 1].get_status_donate_value(matrix_build_type)}"
            )

            for i in status_list[status_list.index(status) + 2 :]:
                buttons[
                    f"🔴{i.value} - "
                    f"{get_donate_value_with_currency(i.get_status_donate_value(matrix_build_type), matrix_build_type)}🔴"
                ] = (
                    f"confirm_donate_🔴_{build_type_str}_"
                    f"{i.get_status_donate_value(matrix_build_type)}"
                )
        else:
            continue

    return buttons
