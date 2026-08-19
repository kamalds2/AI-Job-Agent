from typing import Generic, Type, TypeVar, Optional

from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, db: Session, model: Type[ModelType]):
        self.db = db
        self.model = model

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def get_by_id(self, obj_id: int) -> Optional[ModelType]:
        return (
            self.db.query(self.model)
            .filter(self.model.id == obj_id)
            .first()
        )

    def get_all(self) -> list[ModelType]:
        return self.db.query(self.model).all()

    def update(self):
        self.db.commit()

    def delete(self, obj: ModelType):
        self.db.delete(obj)
        self.db.commit()