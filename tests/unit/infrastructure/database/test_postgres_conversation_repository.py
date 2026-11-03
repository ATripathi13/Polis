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
        filtered = self.records
        for crit in criteria:
            try:
                col_name = crit.left.name
                val = crit.right.value
                filtered = [r for r in filtered if getattr(r, col_name, None) == val]
            except Exception:
                pass
        return FakeQuery(filtered)

    def order_by(self, *expressions):
        return self

    def first(self):
        return self.records[0] if self.records else None

    def all(self):
        return self.records


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def query(self, model):
        assert model is ConversationMemoryModel
        return FakeQuery(self.records)

    def add(self, obj):
        self.added.append(obj)
        self.records.append(obj)

    def commit(self):
        self.committed = True


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


def test_postgres_active_pending_operation_survives_ordinary_exchange_and_reload(monkeypatch):
    """Verify an active pending operation in PostgreSQL survives ordinary exchange and reload."""
    from datetime import timedelta
    from domain.reasoning.value_objects import ConversationContext

    records = []
    monkeypatch.setattr(conversation_module, "SessionLocal", lambda: FakeSession(records))

    repo = PostgreSQLConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    pending = {
        "operation_id": "op-pg-active",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVS",
        "thread_ts": "500.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    # 1. Save initial exchange with pending operation
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVS",
        thread_ts="500.1",
    ).add_exchange(
        user_message="Schedule team sync",
        assistant_message="What time?",
        user_id="U_ALICE",
        pending_operation=pending,
    )
    repo.save(init_ctx)

    # 2. Reload from PostgreSQL
    loaded = repo.get("C_DEVS", "500.1")
    assert loaded is not None
    assert loaded.pending_operation is not None
    assert loaded.pending_operation["operation_id"] == "op-pg-active"
    assert loaded.get_pending_operation() is not None
    assert loaded.get_pending_operation()["operation_id"] == "op-pg-active"

    # 3. Ordinary exchange without clearing
    continued_ctx = loaded.add_exchange(
        user_message="Tomorrow at 2pm",
        assistant_message="Checking availability...",
        user_id="U_ALICE",
    )
    repo.save(continued_ctx)

    # 4. Reload again from PostgreSQL: active pending operation must survive
    reloaded = repo.get("C_DEVS", "500.1")
    assert reloaded is not None
    assert reloaded.pending_operation is not None
    assert reloaded.get_pending_operation() is not None
    assert reloaded.get_pending_operation()["operation_id"] == "op-pg-active"


def test_postgres_explicit_clearing_remains_cleared_after_reload(monkeypatch):
    """Verify explicitly cleared pending operation in PostgreSQL remains cleared after reload."""
    from datetime import timedelta
    from domain.reasoning.value_objects import ConversationContext

    records = []
    monkeypatch.setattr(conversation_module, "SessionLocal", lambda: FakeSession(records))

    repo = PostgreSQLConversationRepository()
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    pending = {
        "operation_id": "op-pg-clear",
        "intent": "calendar_action",
        "user_id": "U_ALICE",
        "channel_id": "C_DEVS",
        "thread_ts": "500.1",
        "created_at_iso": now.isoformat(),
        "expires_at_iso": future.isoformat(),
    }

    # Initial exchange with pending operation
    init_ctx = ConversationContext(
        user_id="U_ALICE",
        channel_id="C_DEVS",
        thread_ts="500.1",
    ).add_exchange(
        user_message="Schedule team sync",
        assistant_message="What time?",
        user_id="U_ALICE",
        pending_operation=pending,
    )
    repo.save(init_ctx)

    # Explicitly clear pending operation
    cleared_ctx = init_ctx.add_exchange(
        user_message="Cancel request",
        assistant_message="Cancelled.",
        user_id="U_ALICE",
        clear_pending=True,
    )
    repo.save(cleared_ctx)

    # Reload from PostgreSQL: must be cleared
    reloaded = repo.get("C_DEVS", "500.1")
    assert reloaded is not None
    assert reloaded.pending_operation is None
    assert reloaded.get_pending_operation() is None

    # Normal follow-up exchange afterwards stays cleared
    normal_ctx = reloaded.add_exchange(
        user_message="What's for lunch?",
        assistant_message="Check cafeteria menu.",
        user_id="U_ALICE",
    )
    repo.save(normal_ctx)
    reloaded_after_normal = repo.get("C_DEVS", "500.1")
    assert reloaded_after_normal is not None
    assert reloaded_after_normal.pending_operation is None
    assert reloaded_after_normal.get_pending_operation() is None


def test_postgres_historical_pending_operations_reconstructed_correctly(monkeypatch):
    """Verify historical pending operations in PostgreSQL records are reconstructed correctly."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=20)

    # Record containing historical exchanges:
    # 1. Alice established pending operation
    # 2. Bob joined the thread and spoke (ordinary exchange without pending op)
    history = [
        {"role": "user", "content": "Schedule sync", "user_id": "U_ALICE"},
        {
            "role": "assistant",
            "content": "What time?",
            "user_id": "U_ALICE",
            "pending_operation": {
                "operation_id": "op-alice-history",
                "intent": "calendar_action",
                "user_id": "U_ALICE",
                "channel_id": "C_SHARED",
                "thread_ts": "600.1",
                "created_at_iso": now.isoformat(),
                "expires_at_iso": future.isoformat(),
            },
        },
        {"role": "user", "content": "Can I attend too?", "user_id": "U_BOB"},
        {
            "role": "assistant",
            "content": "Sure Bob.",
            "user_id": "U_BOB",
            "pending_operation": None,
        },
    ]

    record = SimpleNamespace(
        channel_id="C_SHARED",
        thread_ts="600.1",
        history=history,
        created_at=now,
        updated_at=now,
    )

    session = FakeSession([record])
    monkeypatch.setattr(conversation_module, "SessionLocal", lambda: session)

    repo = PostgreSQLConversationRepository()

    # Load context
    loaded = repo.get("C_SHARED", "600.1")
    assert loaded is not None

    # Bob checking has no pending operation
    assert loaded.get_pending_operation(expected_user_id="U_BOB") is None

    # Alice checking has her historical pending operation safely reconstructed
    alice_op = loaded.get_pending_operation(expected_user_id="U_ALICE")
    assert alice_op is not None
    assert alice_op["operation_id"] == "op-alice-history"

    # Bob checking get_latest on C_SHARED (where Bob was the latest sender) has no pending op
    latest_bob = repo.get_latest("C_SHARED", user_id="U_BOB")
    assert latest_bob is not None
    assert latest_bob.get_pending_operation(expected_user_id="U_BOB") is None

    # Alice DM record where Alice is sender
    dm_record = SimpleNamespace(
        channel_id="D_ALICE",
        thread_ts="700.1",
        history=[
            {"role": "user", "content": "Schedule sync", "user_id": "U_ALICE"},
            {
                "role": "assistant",
                "content": "What time?",
                "user_id": "U_ALICE",
                "pending_operation": {
                    "operation_id": "op-alice-dm-latest",
                    "intent": "calendar_action",
                    "user_id": "U_ALICE",
                    "channel_id": "D_ALICE",
                    "thread_ts": "700.1",
                    "created_at_iso": now.isoformat(),
                    "expires_at_iso": future.isoformat(),
                },
            },
        ],
        created_at=now,
        updated_at=now,
    )
    session.records.append(dm_record)

    latest_alice = repo.get_latest("D_ALICE", user_id="U_ALICE")
    assert latest_alice is not None
    assert latest_alice.get_pending_operation(expected_user_id="U_ALICE")["operation_id"] == "op-alice-dm-latest"
