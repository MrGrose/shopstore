from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select

from src.repositories.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class CRUDBase(Generic[ModelType]):
    def __init__(self, session, model) -> None:
        self.model = model
        self.session = session

    # Возвращает запись по идентификатору.
    async def get_by_id(self, id: int) -> ModelType | None:
        db_result = await self.session.scalars(
            select(self.model).where(self.model.id == id)
        )
        return db_result.first()

    # Возвращает все записи по признаку активности.
    async def get_all(self, flag: bool) -> list[ModelType]:
        db_result_active = await self.session.scalars(
            select(self.model).where(self.model.is_active == flag)
        )
        result_active = list(db_result_active.all())
        return result_active

    # Создает новую запись.
    async def create(self, obj_in: BaseModel) -> ModelType:
        db_obj = self.model(**obj_in.model_dump())
        self.session.add(db_obj)
        await self.session.commit()
        await self.session.refresh(db_obj)
        return db_obj

    # Обновляет существующую запись.
    async def update(self, db_obj: ModelType, obj_in: BaseModel) -> ModelType:
        for field, value in obj_in.model_dump(exclude_unset=True).items():
            setattr(db_obj, field, value)
        self.session.add(db_obj)
        await self.session.commit()
        await self.session.refresh(db_obj)
        return db_obj

    # Удаляет запись по идентификатору.
    async def delete(self, id: int) -> ModelType:
        obj = await self.get_by_id(id)
        if obj is None:
            raise ValueError(f"{self.model.__name__} c id={id} не найден")
        await self.session.delete(obj)
        await self.session.commit()
        return obj
