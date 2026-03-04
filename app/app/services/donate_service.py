import uuid
from datetime import datetime
from typing import Tuple, Any

import loguru
from dependency_injector.wiring import inject

from app.repositories.telegram_user import RepositoryTelegramUser
from app.repositories.matrix import RepositoryMatrix
from app.repositories.donate import RepositoryDonate
from app.models.telegram_user import TelegramUser, DonateStatus, MatrixBuildType
from app.models.matrix import Matrix
from app.services.matrix_service import MatrixService
from app.services.telegram_user_service import TelegramUserService
from app.schemas.matrix import MatrixEntity
from app.utils.matrix import get_matrices_length
from app.utils.matrix import find_first_level_matrix_id
from app.utils.sort import get_reversed_dict


class DonateService:
    def __init__(
            self,
            repository_telegram_user: RepositoryTelegramUser,
            repository_matrix: RepositoryMatrix,
            repository_donate: RepositoryDonate,
    ) -> None:
        self._repository_telegram_user = repository_telegram_user
        self._repository_matrix = repository_matrix
        self._repository_donate = repository_donate

    @staticmethod
    def get_donate_status(
            donate_sum: int,
    ) -> DonateStatus | None:
        if donate_sum in (25, ):
            return DonateStatus.BRONZE
        elif donate_sum in (50, ):
            return DonateStatus.SILVER
        elif donate_sum in (100, ):
            return DonateStatus.GOLD

        return None

    @staticmethod
    def _extend_donations_data(data: dict, sponsor: TelegramUser, donate: int | float):
        if data.get(sponsor):
            data[sponsor] += donate
        else:
            data[sponsor] = donate
        return data

    async def _add_user_to_admin_matrix(
            self,
            donate_sum: int | float,
            status: DonateStatus,
            donations_data: dict,
            matrix_build_type: MatrixBuildType,
            level_length: int,
    ) -> Matrix:

        admin = self._repository_telegram_user.get(is_admin=True)
        admin_matrices = self._repository_matrix.get_user_matrices(
            owner_id=admin.id,
            status=status,
            build_type=matrix_build_type,
        )

        self._extend_donations_data(donations_data, admin, donate_sum)

        matrices_with_empty_places = []
        for matrix in admin_matrices:
            if get_matrices_length(matrix.matrices) < (level_length * level_length) + level_length:
                matrices_with_empty_places.append(matrix)

        if not matrices_with_empty_places:
            return admin_matrices[-1], True

        for matrix in matrices_with_empty_places:
            is_matrix_free_with_donates = self.check_is_matrix_free_with_donates(
                matrix=matrix,
                matrix_build_type=matrix_build_type,
                status=status,
            )
            if is_matrix_free_with_donates:
                return matrix, True

        return matrices_with_empty_places[0], False


    @inject
    async def _send_donate_to_matrix_owner(
            self,
            matrix: Matrix,
            current_user: TelegramUser,
            first_sponsor: TelegramUser,
            donate_sum: int | float,
            status: DonateStatus,
            donations_data: dict,
            matrix_build_type: MatrixBuildType,
            level_length: int,
    ) -> Matrix:
        if len(matrix.matrices.keys()) >= level_length:
            self._extend_donations_data(donations_data, first_sponsor, donate_sum)
            return matrix
        else:
            parent_matrix = self._repository_matrix.get_parent_matrix(
                matrix_id=matrix.id, status=matrix.status
            )

            if not parent_matrix:
                await self._add_user_to_admin_matrix(
                    donate_sum,
                    status,
                    donations_data,
                    matrix_build_type=matrix_build_type,
                    level_length=level_length
                )
                return matrix

            parent_owner = self._repository_telegram_user.get(id=parent_matrix.owner_id)
            self._extend_donations_data(donations_data, parent_owner, donate_sum)

            return matrix

    async def get_matrix_to_add_user(
            self,
            first_sponsor: TelegramUser,
            current_user: TelegramUser,
            donate_sum: int,
            status: DonateStatus,
            donations_data: dict,
            matrix_build_type: MatrixBuildType,
    ) -> Tuple[Matrix, bool]:
        level_length = 2 if matrix_build_type == MatrixBuildType.BINARY else 3
        second_level_length = level_length * level_length
        matrix_max_length = second_level_length + level_length

        first_sponsor_matrices = self._repository_matrix.get_user_matrices(
            owner_id=first_sponsor.id,
            status=status,
            build_type=matrix_build_type,
        )

        if first_sponsor.is_admin:
            return await self._add_user_to_admin_matrix(
                donate_sum,
                status,
                donations_data,
                matrix_build_type=matrix_build_type,
                level_length=level_length,
            )

        matrices_with_empty_places = []
        for matrix in first_sponsor_matrices:
            has_matrix_empty_places = get_matrices_length(matrix.matrices) < matrix_max_length
            loguru.logger.info(f"has_matrix_empty_places {matrix.id}: {has_matrix_empty_places}")

            if has_matrix_empty_places:
                matrices_with_empty_places.append(matrix)

        loguru.logger.info(f"\n")

        if not matrices_with_empty_places:
            return await self._find_free_matrix(
                current_user,
                donate_sum,
                status,
                donations_data,
                matrix_build_type=matrix_build_type,
                level_length=level_length,
            )


        for matrix in matrices_with_empty_places:
            is_matrix_free_with_donates = self.check_is_matrix_free_with_donates(
                matrix=matrix,
                matrix_build_type=matrix_build_type,
                status=status,
            )
            loguru.logger.info(f"is_matrix_free_with_donates {matrix.id}: {is_matrix_free_with_donates}")

            if is_matrix_free_with_donates:
                return await self._send_donate_to_matrix_owner(
                    matrix,
                    current_user,
                    first_sponsor,
                    donate_sum,
                    status,
                    donations_data,
                    matrix_build_type=matrix_build_type,
                    level_length=level_length,
                ), True

        return matrices_with_empty_places[0], False



    @inject
    async def _find_free_matrix(
            self,
            user_to_add: TelegramUser,
            donate_sum: int | float,
            status: DonateStatus,
            donations_data: dict,
            matrix_build_type: MatrixBuildType,
            level_length: int,
    ):
        matrix_max_length = (level_length * level_length) + level_length

        while True:
            next_sponsor = self._repository_telegram_user.get(
                user_id=user_to_add.sponsor_user_id
            )
            if next_sponsor is None:
                loguru.logger.info("next")
                return await self._add_user_to_admin_matrix(
                    donate_sum,
                    status,
                    donations_data,
                    matrix_build_type=matrix_build_type,
                    level_length=level_length,
                )

            if next_sponsor.get_status(matrix_build_type) == DonateStatus.NOT_ACTIVE or not (
                int(status.get_status_donate_value()) <= int(
                    next_sponsor.get_status(matrix_build_type)
                    .get_status_donate_value()
                )
            ):
                user_to_add = next_sponsor
                continue

            next_sponsor_matrices = self._repository_matrix.get_user_matrices(
                owner_id=next_sponsor.id,
                status=status,
                build_type=matrix_build_type,
            )

            matrices_with_empty_places = []
            for matrix in next_sponsor_matrices:
                if get_matrices_length(matrix.matrices) < matrix_max_length:
                    matrices_with_empty_places.append(matrix)

            if not matrices_with_empty_places:
                loguru.logger.info("no matrices")
                user_to_add = next_sponsor
                continue

            for matrix in matrices_with_empty_places:
                is_matrix_free_with_donates = self.check_is_matrix_free_with_donates(
                    matrix=matrix,
                    matrix_build_type=matrix_build_type,
                    status=status,
                )
                if is_matrix_free_with_donates:
                    await self._send_donate_to_matrix_owner(
                        matrix,
                        user_to_add,
                        next_sponsor,
                        donate_sum,
                        status,
                        donations_data,
                        matrix_build_type=matrix_build_type,
                        level_length=level_length,
                    )
                    return matrix, True

            return matrices_with_empty_places[0], False


    def check_is_matrix_free_with_donates(
            self,
            matrix: Matrix,
            matrix_build_type: MatrixBuildType,
            status: DonateStatus
    ):
        current_matrix = matrix
        level_length = 2 if matrix_build_type == MatrixBuildType.BINARY else 3
        second_level_length = level_length * level_length

        first_level_current_matrix_length = len(list(current_matrix.matrices.keys()))
        current_matrix_donates_count = self._repository_donate.get_count(
            matrix_id=current_matrix.id,
            is_confirmed=False,
            is_canceled=False,
        )

        if first_level_current_matrix_length < level_length:
            first_level_empty_places_count = level_length - first_level_current_matrix_length

            if first_level_empty_places_count <= current_matrix_donates_count:
                return False

            parent_matrix = self._repository_matrix.get_parent_matrix(
                matrix_id=current_matrix.id,
                status=status,
            )
            if not parent_matrix:
                return True
            parent_first_level_matrices = self._repository_matrix.get_matrices_by_ids_list(
                matrices_ids=list(parent_matrix.matrices.keys())
            )

            sorted_parent_first_level_matrices = sorted(
                parent_first_level_matrices,
                key=lambda x: x.created_at,
            )
            current_matrix_index = sorted_parent_first_level_matrices.index(current_matrix)

            p_matrix_max_length_till_current_matrix = (
                (level_length * (current_matrix_index + 1)) + level_length
            )
            p_matrix_length_till_current_matrix = len(parent_first_level_matrices)

            for parent_first_level_matrix in sorted_parent_first_level_matrices[:current_matrix_index + 1]:
                p_matrix_length_till_current_matrix += len(list(parent_first_level_matrix.matrices.keys()))

            p_matrix_empty_places_count_till_current_matrix = (
                p_matrix_max_length_till_current_matrix - p_matrix_length_till_current_matrix
            )
            donate_matrices_ids = [
                matrix.id for matrix in parent_first_level_matrices[:current_matrix_index]
                if len(list(matrix.matrices.keys())) < level_length
            ]
            donate_matrices_ids.append(parent_matrix.id)

            matrices_donates = self._repository_donate.get_donates_by_matrices_ids(
                matrices_ids=donate_matrices_ids,
                is_confirmed=False,
                is_canceled=False,
            )
            total_donates_count = len(matrices_donates) + current_matrix_donates_count

            if p_matrix_empty_places_count_till_current_matrix <= total_donates_count:
                return False

            return True

        second_level_current_matrix_length = get_matrices_length(current_matrix.matrices) - level_length
        second_level_empty_places_count = second_level_length - second_level_current_matrix_length

        if second_level_empty_places_count <= current_matrix_donates_count:
            return False

        first_level_matrices = self._repository_matrix.get_matrices_by_ids_list(
            matrices_ids=list(matrix.matrices.keys())
        )
        sorted_first_level_matrices = sorted(first_level_matrices, key=lambda x: x.created_at)

        donate_first_level_matrices_ids = [
            matrix.id for matrix in sorted_first_level_matrices
            if len(list(matrix.matrices.keys())) < level_length
        ]
        first_level_matrices_donates = self._repository_donate.get_donates_by_matrices_ids(
            matrices_ids=donate_first_level_matrices_ids,
            is_confirmed=False,
            is_canceled=False,
        )
        total_donates_count = len(first_level_matrices_donates) + current_matrix_donates_count
        if second_level_empty_places_count <= total_donates_count:
            return False

        return True
























