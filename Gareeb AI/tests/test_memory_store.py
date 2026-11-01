"""Persistent memory tests (FR-08, PRD section 12)."""
import time
import pytest

from core.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    s = MemoryStore(db_path=str(db), max_conversations=5,
                    max_messages_per_conversation=10,
                    cleanup_days=30, auto_cleanup=True)
    yield s
    s.close()


# ----------------------------------------------------------------------
# Conversations
# ----------------------------------------------------------------------
class TestConversations:
    def test_create_and_list(self, store):
        cid = store.create_conversation("Test chat")
        convs = store.list_conversations()
        assert len(convs) == 1
        assert convs[0]["title"] == "Test chat"
        assert convs[0]["id"] == cid

    def test_add_and_get_messages(self, store):
        cid = store.create_conversation("Chat")
        store.add_message(cid, "user", "Hello MJ")
        store.add_message(cid, "assistant", "Hi there!")

        msgs = store.get_messages(cid)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "Hello MJ"

    def test_recent_context_for_model(self, store):
        cid = store.create_conversation("Chat")
        for i in range(5):
            store.add_message(cid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        ctx = store.recent_context(cid, max_messages=3)
        assert len(ctx) == 3
        assert all(set(m.keys()) == {"role", "content"} for m in ctx)

    def test_message_limit_trims_oldest(self, store):
        cid = store.create_conversation("Chat")
        for i in range(25):
            store.add_message(cid, "user", f"msg{i}")
        msgs = store.get_messages(cid)
        assert len(msgs) == 10  # capped by max_messages_per_conversation
        assert msgs[0]["content"] == "msg15"  # oldest trimmed

    def test_conversation_limit_trims(self, store):
        for i in range(10):
            store.create_conversation(f"C{i}")
            time.sleep(0.01)
        # Trimming only happens on record; force via internal call.
        store._trim_conversation_count()
        assert len(store.list_conversations()) <= 5

    def test_delete_conversation(self, store):
        cid = store.create_conversation("Bye")
        store.add_message(cid, "user", "x")
        assert store.delete_conversation(cid)
        assert store.list_conversations() == []
        assert store.get_messages(cid) == []

    def test_clear_history(self, store):
        cid = store.create_conversation("A")
        store.add_message(cid, "user", "one")
        cid2 = store.create_conversation("B")
        store.add_message(cid2, "user", "two")
        removed = store.clear_history()
        assert removed >= 2
        assert store.list_conversations() == []

    def test_rename(self, store):
        cid = store.create_conversation("Old")
        store.rename_conversation(cid, "New title")
        assert store.list_conversations()[0]["title"] == "New title"


# ----------------------------------------------------------------------
# Preferences
# ----------------------------------------------------------------------
class TestPreferences:
    def test_set_get_roundtrip(self, store):
        store.set_preference("theme", "dark")
        assert store.get_preference("theme") == "dark"

    def test_default_when_missing(self, store):
        assert store.get_preference("nope", 42) == 42

    def test_complex_values(self, store):
        store.set_preference("window", {"x": 10, "y": 20, "w": 800})
        assert store.get_preference("window")["w"] == 800

    def test_all_preferences(self, store):
        store.set_preference("a", 1)
        store.set_preference("b", [1, 2])
        all_prefs = store.all_preferences()
        assert all_prefs["a"] == 1
        assert all_prefs["b"] == [1, 2]


# ----------------------------------------------------------------------
# Task history
# ----------------------------------------------------------------------
class TestTaskHistory:
    def test_record_task(self, store):
        tid = store.record_task("Open notepad", "completed",
                                steps=[{"id": 1, "status": "done"}],
                                finished=True)
        tasks = store.recent_tasks()
        assert len(tasks) == 1
        assert tasks[0]["status"] == "completed"
        assert tasks[0]["steps"][0]["id"] == 1
        assert tasks[0]["finished_at"] is not None

    def test_update_task(self, store):
        tid = store.record_task("Multi", "running")
        store.update_task(tid, "failed",
                          steps=[{"id": 1, "status": "failed"}],
                          finished=True)
        task = store.recent_tasks()[0]
        assert task["status"] == "failed"
        assert task["finished_at"] is not None


# ----------------------------------------------------------------------
# Retention & stats
# ----------------------------------------------------------------------
class TestRetention:
    def test_cleanup_old_conversations(self, tmp_path):
        s = MemoryStore(db_path=str(tmp_path / "r.db"), cleanup_days=0,
                        auto_cleanup=True)
        try:
            cid = s.create_conversation("ancient")
            # Force the record into the past.
            conn = s._connect()
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                         (time.time() - 10 * 86400, cid))
            conn.commit()
            removed = s.cleanup_old()
            assert removed == 1
            assert s.list_conversations() == []
        finally:
            s.close()

    def test_cleanup_disabled(self, tmp_path):
        s = MemoryStore(db_path=str(tmp_path / "r2.db"), auto_cleanup=False)
        try:
            s.create_conversation("keep")
            assert s.cleanup_old() == 0
            assert len(s.list_conversations()) == 1
        finally:
            s.close()

    def test_stats(self, store):
        cid = store.create_conversation("S")
        store.add_message(cid, "user", "hello")
        store.set_preference("k", "v")
        store.record_task("t", "completed", finished=True)

        stats = store.stats()
        assert stats["conversations"] == 1
        assert stats["messages"] == 1
        assert stats["preferences"] == 1
        assert stats["tasks"] == 1
        assert stats["db_bytes"] > 0
