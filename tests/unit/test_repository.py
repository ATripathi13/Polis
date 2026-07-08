from domain.common.entity import Entity
from domain.common.identifier import Identifier
from domain.common.repository import Repository


class DummyEntity(Entity):
    pass


class DummyRepository(Repository[DummyEntity]):
    def __init__(self) -> None:
        self._items: dict[str, DummyEntity] = {}

    def get(self, identifier: Identifier) -> DummyEntity | None:
        return self._items.get(str(identifier.graph_id))

    def save(self, entity: DummyEntity) -> None:
        self._items[str(entity.graph_id)] = entity

    def delete(self, identifier: Identifier) -> None:
        self._items.pop(str(identifier.graph_id), None)

    def exists(self, identifier: Identifier) -> bool:
        return str(identifier.graph_id) in self._items


def test_repository_save_and_get() -> None:
    repository = DummyRepository()

    entity = DummyEntity()

    repository.save(entity)

    assert repository.exists(entity.identifier)

    loaded = repository.get(entity.identifier)

    assert loaded == entity