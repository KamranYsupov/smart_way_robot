import enum

from sqlalchemy import (
    Column,
    Integer,
    Float,
    ForeignKey,
    Enum,
    UUID,
    Boolean,
    BigInteger,
    UniqueConstraint,
    String,
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.models.mixins import TimestampedMixin, UUIDMixin, AbstractTelegramUser


class MatrixBuildType(enum.Enum):
    BINARY = "Бинар"
    TRINARY = "Тринар"


class DonateStatus(enum.Enum):
    NOT_ACTIVE = "Не активирован"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"

    def get_status_donate_value(
            self,
            matrix_build_type: MatrixBuildType = MatrixBuildType.BINARY
    ) -> int:
        """Получение суммы доната"""
        donate_status_data = self.get_donate_status_data(matrix_build_type)

        return donate_status_data.get(self)

    @classmethod
    def get_donate_status_data(
            cls,
            matrix_build_type: MatrixBuildType = MatrixBuildType.BINARY
    ) -> dict:
        if matrix_build_type == MatrixBuildType.TRINARY:
            donate_status_data = cls.get_trinary_donations_data()
        elif matrix_build_type == MatrixBuildType.BINARY:
            donate_status_data = cls.get_binary_donations_data()
        else:
            raise TypeError("Неверный объект типа \"MatrixBuildType\"")

        return donate_status_data

    @classmethod
    def get_status_list(cls) -> list:
        return [
            cls.BRONZE,
            cls.SILVER,
            cls.GOLD,
        ]

    @classmethod
    def get_binary_donations_data(cls) -> dict:
        return {
            cls.BRONZE: 25,
            cls.SILVER: 50,
            cls.GOLD: 100,
        }

    @classmethod
    def get_trinary_donations_data(cls) -> dict:
        return {
            cls.BRONZE: 30,
            cls.SILVER: 100,
            cls.GOLD: 300,
        }

status_list = DonateStatus.get_status_list()
status_emoji_list = [
    "1️⃣" ,
    "2️⃣" ,
    "3️⃣" ,
]
statuses_colors_data = {
    DonateStatus.BRONZE : "🟠",
    DonateStatus.SILVER: "⚪",
    DonateStatus.GOLD: "🟡",
}

class TelegramUser(UUIDMixin, TimestampedMixin, AbstractTelegramUser, Base):
    """Модель телеграм пользователя"""

    __tablename__ = "telegram_users"

    trinary_status = Column(Enum(DonateStatus), default=DonateStatus.NOT_ACTIVE)
    binary_status = Column(Enum(DonateStatus), default=DonateStatus.NOT_ACTIVE)
    sponsor_user_id = Column(
        BigInteger,
        ForeignKey("telegram_users.user_id"),
        nullable=True,
        index=True,
    )
    invites_count = Column(Integer, default=0)
    donates_sum = Column(Float, default=0.0)
    trinary_bill = Column(Float, default=0.0)
    binary_bill = Column(Float, default=0.0)
    is_admin = Column(Boolean, index=True, default=False)
    wallet_address = Column(String, nullable=True)
    depth_level = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)

    sponsor = relationship(
        "TelegramUser",
        remote_side="TelegramUser.user_id",
        backref="invited_users"
    )
    transactions = relationship(
        "Transaction",
        back_populates="telegram_user"
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="unique_user_id"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            self.username if self.username
            else f"Пользователь: {self.user_id}"
        )

    def get_status(self, matrix_build_type: MatrixBuildType):
        if matrix_build_type == MatrixBuildType.TRINARY:
            return self.trinary_status
        if matrix_build_type == MatrixBuildType.BINARY:
            return self.binary_status

        return None

    def set_status(
            self,
            status: DonateStatus,
            matrix_build_type: MatrixBuildType
    ):
        if matrix_build_type == MatrixBuildType.TRINARY:
            self.trinary_status = status
        if matrix_build_type == MatrixBuildType.BINARY:
            self.binary_status = status

    def get_bill(self, matrix_build_type: MatrixBuildType):
        if matrix_build_type == MatrixBuildType.TRINARY:
            return self.trinary_bill
        if matrix_build_type == MatrixBuildType.BINARY:
            return self.binary_bill

        return None

    def add_to_bill(
            self,
            value: int,
            matrix_build_type: MatrixBuildType
    ):
        if matrix_build_type == MatrixBuildType.TRINARY:
            self.trinary_bill += value
        if matrix_build_type == MatrixBuildType.BINARY:
            self.binary_bill += value
