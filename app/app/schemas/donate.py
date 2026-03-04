import uuid

from pydantic import BaseModel, Field
from app.models.telegram_user import MatrixBuildType


class DonateEntity(BaseModel):
    """Представление модели Donate"""

    telegram_user_id: uuid.UUID = Field(title="ID пользователя")
    quantity: float = Field(title="Размер доната")
    is_confirmed: bool = Field(title="Подтвержден", default=False)
    matrix_id: uuid.UUID = Field(title="ID матрицы")
    matrix_build_type: MatrixBuildType | str = Field(title="Тип построения")



class DonateTransactionEntity(BaseModel):
    sponsor_id: uuid.UUID = Field(title="ID спонсора")
    donate_id: uuid.UUID = Field(title="ID доната")
    is_confirmed: bool = Field(title="Подтвержден", default=False)
    quantity: float = Field(title="Размер доната")
