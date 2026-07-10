from domain.reasoning import (
    ReasoningPolicyRegistry,
)

from domain.reasoning.policies import (
    MentionPolicy,
)
from domain.reasoning.policies import (
    ReasoningPolicy,
)


class DummyPolicy(ReasoningPolicy):

    @property
    def priority(self):
        return 10

    def evaluate(self, context):
        return None

def test_register_policy():

    registry = ReasoningPolicyRegistry()

    registry.register(
        MentionPolicy(),
    )

    assert len(registry.policies) == 1

    assert isinstance(
        registry.policies[0],
        MentionPolicy,
    )

def test_registry_orders_policies():

    registry = ReasoningPolicyRegistry()

    registry.register(
        MentionPolicy(),
    )

    registry.register(
        DummyPolicy(),
    )

    assert isinstance(
        registry.policies[0],
        DummyPolicy,
    )

    assert isinstance(
        registry.policies[1],
        MentionPolicy,
    )