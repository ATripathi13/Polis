from datetime import datetime, timezone
from types import SimpleNamespace

from infrastructure.database import (
    postgres_conversation_repository as conversation_module,
)
from infrastructure.database.models import ConversationMemoryModel
from infrastructure.database.postgres_conversation_repository import (
    PostgreSQLConversationRepository,
)


class FakeQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *criteria):
        return self

    def order_by(self, *expressions):
        return self

    def all(self):
        return self.records


class FakeSession:
    def __init__(self, records):
        self.query_instance = FakeQuery(records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def query(self, model):
        assert model is ConversationMemoryModel
        return self.query_instance


def make_record(thread_ts, user_id, question):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        channel_id="D_SHARED",
        thread_ts=thread_ts,
        history=[
            {
                "role": "user",
                "content": question,
                "user_id": user_id,
            },
            {
                "role": "assistant",
                "content": f"Answer to {question}",
            },
        ],
        created_at=now,
        updated_at=now,
    )


def test_get_latest_filters_records_by_sender(monkeypatch):
    newest_bob_record = make_record("200.1", "U_BOB", "Bob's question")
    older_alice_record = make_record("100.1", "U_ALICE", "Alice's question")

    session = FakeSession([newest_bob_record, older_alice_record])
    monkeypatch.setattr(
        conversation_module,
        "SessionLocal",
        lambda: session,
    )

    repo = PostgreSQLConversationRepository()

    alice_context = repo.get_latest("D_SHARED", user_id="U_ALICE")
    bob_context = repo.get_latest("D_SHARED", user_id="U_BOB")
    unknown_context = repo.get_latest("D_SHARED", user_id="U_CHARLIE")

    assert alice_context is not None
    assert alice_context.thread_ts == "100.1"
    assert alice_context.history[0]["user_id"] == "U_ALICE"

    assert bob_context is not None
    assert bob_context.thread_ts == "200.1"
    assert bob_context.history[0]["user_id"] == "U_BOB"

    assert unknown_context is None

def test_in_memory_and_postgres_have_equivalent_get_latest_semantics(monkeypatch):
    """Verify that InMemory and PostgreSQL repositories implement identical get_latest() filtering semantics."""
    from infrastructure.database.conversation_repository import InMemoryConversationRepository
    from domain.reasoning.value_objects import ConversationContext

    # 1. Setup PostgreSQL mock
    bob_record = make_record("200.1", "U_BOB", "Bob's question")
    alice_record = make_record("100.1", "U_ALICE", "Alice's question")

    session = FakeSession([bob_record, alice_record])
    monkeypatch.setattr(
        conversation_module,
        "SessionLocal",
        lambda: session,
    )

    pg_repo = PostgreSQLConversationRepository()

    # 2. Setup InMemory repository with identical data
    mem_repo = InMemoryConversationRepository()
    alice_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="D_SHARED",
        thread_ts="100.1",
        channel_type="im",
    ).add_exchange("Alice's question", "Answer to Alice's question")

    bob_ctx = ConversationContext(
        user_id="U_BOB",
        channel_id="D_SHARED",
        thread_ts="200.1",
        channel_type="im",
    ).add_exchange("Bob's question", "Answer to Bob's question")

    mem_repo.save(alice_ctx)
    mem_repo.save(bob_ctx)

    # 3. Compare get_latest for Alice
    pg_alice = pg_repo.get_latest("D_SHARED", user_id="U_ALICE")
    mem_alice = mem_repo.get_latest("D_SHARED", user_id="U_ALICE")
    assert pg_alice is not None
    assert mem_alice is not None
    assert pg_alice.thread_ts == mem_alice.thread_ts == "100.1"
    assert pg_alice.history[0]["content"] == mem_alice.history[0]["content"] == "Alice's question"

    # 4. Compare get_latest for Bob
    pg_bob = pg_repo.get_latest("D_SHARED", user_id="U_BOB")
    mem_bob = mem_repo.get_latest("D_SHARED", user_id="U_BOB")
    assert pg_bob is not None
    assert mem_bob is not None
    assert pg_bob.thread_ts == mem_bob.thread_ts == "200.1"
    assert pg_bob.history[0]["content"] == mem_bob.history[0]["content"] == "Bob's question"

    # 5. Compare get_latest for Charlie (unseen user)
    pg_charlie = pg_repo.get_latest("D_SHARED", user_id="U_CHARLIE")
    mem_charlie = mem_repo.get_latest("D_SHARED", user_id="U_CHARLIE")
    assert pg_charlie is None
    assert mem_charlie is None

    # 6. Compare get_latest without user_id (returns latest conversation)
    pg_latest = pg_repo.get_latest("D_SHARED")
    mem_latest = mem_repo.get_latest("D_SHARED")
    assert pg_latest is not None
    assert mem_latest is not None
    assert pg_latest.thread_ts == mem_latest.thread_ts == "200.1"
