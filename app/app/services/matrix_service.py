import datetime
import uuid
from typing import Tuple, Any

import loguru

from app.models.telegram_user import DonateStatus, status_list
from app.repositories.matrix import RepositoryMatrix
from app.models import Matrix
from app.schemas.matrix import MatrixEntity
from app.utils.matrix import get_sorted_matrices
from app.utils.pagination import Paginator
from app.models.telegram_user import TelegramUser
from app.repositories.telegram_user import RepositoryTelegramUser
from app.utils.matrix import (
    get_matrices_length,
    get_matrices_list,
    get_my_team_telegram_usernames,
)
from app.utils.sort import get_sorted_objects_by_ids
from app.utils.matrix import find_first_level_matrix_id
from app.tasks.matrix import send_matrix_first_level_notification_task
from app.models.telegram_user import MatrixBuildType


class MatrixService:
    def __init__(
            self,
            repository_matrix: RepositoryMatrix,
            repository_telegram_user: RepositoryTelegramUser,
    ) -> None:
        self._repository_matrix = repository_matrix
        self._repository_telegram_user = repository_telegram_user

    async def get_list(self) -> list[Matrix]:
        return self._repository_matrix.list()

    async def get_matrix(self, **kwargs) -> Matrix:
        return self._repository_matrix.get(**kwargs)

    async def get_user_matrices(
            self,
            owner_id: uuid.UUID,
            status: DonateStatus | None = None,
            build_type: MatrixBuildType | None = None,
    ) -> list[Matrix]:
        return self._repository_matrix.get_user_matrices(
            owner_id=owner_id,
            status=status,
            build_type=build_type
        )

    async def get_parent_matrix(
            self, matrix_id: Matrix.id, status: DonateStatus, return_all: bool = False
    )-> Matrix:
        return self._repository_matrix.get_parent_matrix(
            matrix_id=matrix_id, status=status, return_all=return_all
        )

    async def create_matrix(self, matrix: MatrixEntity) -> Matrix:
        return self._repository_matrix.create(obj_in=matrix.model_dump())

    async def delete(self, obj_id: uuid.UUID):
        self._repository_matrix.delete(obj_id=obj_id)

    def get_matrix_telegram_users(
            self,
            matrix: Matrix
    ) -> tuple[list[TelegramUser], int]:
        first_matrices_ids, second_matrices_ids = get_matrices_list(matrix.matrices)

        matrices_ids = first_matrices_ids + second_matrices_ids

        first_matrices = self._repository_matrix.get_matrices_by_ids_list(first_matrices_ids)
        second_matrices = self._repository_matrix.get_matrices_by_ids_list(second_matrices_ids)
        first_sorted_matrices = sorted(get_sorted_objects_by_ids(first_matrices, first_matrices_ids),
                                       key=lambda x: x.created_at)
        second_sorted_matrices = sorted(get_sorted_objects_by_ids(second_matrices, second_matrices_ids),
                                        key=lambda x: x.created_at)

        telegram_users_ids = [
            matrix.owner_id if matrix else 0 for matrix in (first_sorted_matrices + second_sorted_matrices)
        ]
        telegram_users = self._repository_telegram_user.get_telegram_users_by_user_ids_list(telegram_users_ids)
        sorted_telegram_users = get_sorted_objects_by_ids(telegram_users, telegram_users_ids)

        return sorted_telegram_users, len(first_matrices_ids)

    async def add_to_matrix(
            self,
            matrix_to_add: Matrix,
            created_matrix: Matrix,
            current_user
    ) -> None:
        current_time = datetime.datetime.now()
        created_matrix.created_at = current_time
        build_type = matrix_to_add.build_type
        level_length = 2 if build_type == MatrixBuildType.BINARY else 3
        second_level_length = level_length * level_length
        matrix_max_length = level_length + second_level_length

        matrix_owner = self._repository_telegram_user.get(id=matrix_to_add.owner_id)
        if get_matrices_length(matrix_to_add.matrices) == matrix_max_length and matrix_owner.is_admin:
            matrix_to_add_dict = {
                "owner_id": matrix_owner.id,
                "status": matrix_to_add.status,
                "build_type": build_type,
            }
            matrix_to_add_entity = MatrixEntity(**matrix_to_add_dict)
            matrix_to_add = self._repository_matrix.create(obj_in=matrix_to_add_entity)
            (matrix_to_add.matrices,
             matrix_to_add.matrix_telegram_usernames,
             matrix_to_add.telegram_users) = {}, {}, []

        matrix_json = {str(created_matrix.id): []}
        matrix_telegram_user_json = {
            f"{current_user.username} {created_matrix.id} {current_time}": []
        }
        if len(matrix_to_add.matrices.keys()) < level_length:
            matrix_to_add.telegram_users.append(current_user.user_id)
            matrix_to_add.matrices.update(matrix_json)
            matrix_to_add.matrix_telegram_usernames.update(matrix_telegram_user_json)

            send_matrix_first_level_notification_task.delay(
                matrix_id=matrix_to_add.id,
                matrix_owner_user_id=matrix_owner.user_id,
            )

            parent_matrix = self._repository_matrix.get_parent_matrix(
                matrix_id=matrix_to_add.id, status=matrix_to_add.status
            )
            if not parent_matrix:
                return

            parent_matrix.matrices[str(matrix_to_add.id)].append(str(created_matrix.id))

            (parent_matrix.matrix_telegram_usernames[
                     f"{matrix_owner.username} {matrix_to_add.id} {matrix_to_add.created_at}"
                 ].append(f"{current_user.username} {created_matrix.id} {current_time}"))

        else:
            first_level_matrices_ids = [
                uuid.UUID(matrix_id) for matrix_id in list(matrix_to_add.matrices.keys())
            ]
            first_level_matrices = self._repository_matrix.get_matrices_by_ids_list(
                first_level_matrices_ids
            )
            sorted_first_level_matrices = sorted(first_level_matrices, key=lambda x: x.created_at)

            for first_level_matrix in sorted_first_level_matrices:
                if len(first_level_matrix.matrices.keys()) < level_length:
                    first_level_matrix_owner = self._repository_telegram_user.get(
                        id=first_level_matrix.owner_id
                    )

                    first_level_matrix.matrices.update(matrix_json)
                    first_level_matrix.matrix_telegram_usernames.update(matrix_telegram_user_json)

                    matrix_to_add.telegram_users.append(current_user.user_id)
                    matrix_to_add.matrices[str(first_level_matrix.id)].append(str(created_matrix.id))
                    (matrix_to_add.matrix_telegram_usernames[
                         f"{first_level_matrix_owner.username} {first_level_matrix.id} {first_level_matrix.created_at}"
                     ]
                     .append(f"{current_user.username} {created_matrix.id} {current_time}"))

                    send_matrix_first_level_notification_task.delay(
                        matrix_id=first_level_matrix.id,
                        matrix_owner_user_id=first_level_matrix_owner.user_id,
                    )
                    break
