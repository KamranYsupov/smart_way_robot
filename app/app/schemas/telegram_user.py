from pydantic import BaseModel, Field

from app.models.telegram_user import DonateStatus


class TelegramUserEntity(BaseModel):
    """Модель пользователя"""

    user_id: int = Field(title="ID пользователя")
    username: str | None = Field(title="Username", default=None)
    first_name: str | None = Field(title="Имя", default=None)
    last_name: str | None = Field(title="Фамилия", default=None)
    sponsor_user_id: int | None = Field(title="ID спонсора", default=None)
    trinary_status: DonateStatus | str = Field(
        title="Тринарный статус", default=DonateStatus.NOT_ACTIVE
    )
    binary_status: DonateStatus | str = Field(
        title="Бинарный статус", default=DonateStatus.NOT_ACTIVE
    )
    invites_count: int = Field(title="Число приглашений", default=0)
    donates_sum: int = Field(title="Сумма донатов", default=0)
    trinary_bill: int = Field(title="Тринарный счет", default=0)
    binary_bill: int = Field(title="Бинарный счет", default=0)
    is_admin: bool = Field(title="Супер пользователь", default=False)
    depth_level: int = Field(title="Уровень глубины")
    is_banned: bool = Field(title="Заблокирован", default=False)
