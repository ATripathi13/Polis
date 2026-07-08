from domain.common.aggregate import AggregateRoot


class DummyAggregate(AggregateRoot):
    pass


def test_aggregate_root() -> None:
    aggregate = DummyAggregate()

    assert aggregate.graph_id is not None