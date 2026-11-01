"""Tool dispatcher tests (FR-04, FR-06, PRD section 12)."""
import pytest
from pathlib import Path

from services.tool_dispatcher import ToolDispatcher, ToolDispatchError
from utils.file_utils import FileUtils


@pytest.fixture
def files():
    return FileUtils(config_manager=None)


@pytest.fixture
def dispatcher(files):
    return ToolDispatcher(automation_service=None,
                          screen_analyzer=None,
                          file_utils=files)


class TestDispatchBasics:
    def test_unknown_action_rejected(self, dispatcher):
        with pytest.raises(ToolDispatchError):
            dispatcher.dispatch("format_disk", {})

    def test_supported_actions_listed(self, dispatcher):
        actions = dispatcher.supported_actions
        assert "open_app" in actions
        assert "create_file" in actions
        assert "capture_screen" in actions

    def test_missing_service_fails_clearly(self, dispatcher):
        # Automation service is None in this fixture.
        with pytest.raises(ToolDispatchError) as err:
            dispatcher.dispatch("open_app", {"app": "notepad"})
        assert "not available" in str(err.value)

    def test_missing_params_reported(self, dispatcher):
        with pytest.raises(ToolDispatchError) as err:
            dispatcher.dispatch("open_app", {})
        assert "app" in str(err.value)


class TestFileActions:
    def test_create_file_verified(self, dispatcher, tmp_path):
        target = tmp_path / "hello.txt"
        result = dispatcher.dispatch("create_file", {
            "path": str(target), "content": "Hello MJ",
        })
        assert result["created"] is True
        assert result["verified"] is True
        assert target.read_text(encoding="utf-8") == "Hello MJ"

    def test_create_file_without_path_fails(self, dispatcher):
        with pytest.raises(ToolDispatchError):
            dispatcher.dispatch("create_file", {"content": "x"})

    def test_refuses_silent_overwrite(self, dispatcher, tmp_path):
        target = tmp_path / "exists.txt"
        target.write_text("original", encoding="utf-8")
        with pytest.raises(ToolDispatchError) as err:
            dispatcher.dispatch("create_file", {
                "path": str(target), "content": "new",
            })
        assert "already exists" in str(err.value)
        # Original content untouched.
        assert target.read_text(encoding="utf-8") == "original"

    def test_read_file(self, dispatcher, tmp_path):
        target = tmp_path / "readme.txt"
        target.write_text("content here", encoding="utf-8")
        result = dispatcher.dispatch("read_file", {"path": str(target)})
        assert result["content"] == "content here"

    def test_read_truncates_long_content(self, dispatcher, tmp_path):
        target = tmp_path / "long.txt"
        target.write_text("y" * 20000, encoding="utf-8")
        result = dispatcher.dispatch("read_file",
                                     {"path": str(target), "max_chars": 100})
        assert len(result["content"]) == 100
        assert result["truncated"] is True

    def test_create_folder_verified(self, dispatcher, tmp_path):
        folder = tmp_path / "new_folder"
        result = dispatcher.dispatch("create_folder", {"path": str(folder)})
        assert result["verified"] is True
        assert folder.is_dir()

    def test_copy_and_search(self, dispatcher, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("findme unique_token", encoding="utf-8")
        dispatcher.dispatch("copy_file", {
            "src_path": str(src), "dst_path": str(tmp_path / "b.txt"),
        })
        result = dispatcher.dispatch("search_files", {
            "directory": str(tmp_path), "query": "unique_token",
        })
        assert result["count"] == 2  # a.txt and b.txt

    def test_rename_file(self, dispatcher, tmp_path):
        src = tmp_path / "old.txt"
        src.write_text("x", encoding="utf-8")
        result = dispatcher.dispatch("rename_file", {
            "path": str(src), "new_name": "new.txt",
        })
        assert (tmp_path / "new.txt").exists()
        assert result["renamed"] is True

    def test_read_missing_file_fails(self, dispatcher, tmp_path):
        with pytest.raises(Exception):
            dispatcher.dispatch("read_file",
                                {"path": str(tmp_path / "ghost.txt")})


class TestScreenActions:
    def test_capture_without_service(self, dispatcher):
        with pytest.raises(ToolDispatchError):
            dispatcher.dispatch("capture_screen", {})

    def test_read_without_service(self, dispatcher):
        with pytest.raises(ToolDispatchError):
            dispatcher.dispatch("read_screen", {})


class TestNoOpActions:
    def test_respond_returns_text(self, dispatcher):
        result = dispatcher.dispatch("respond", {"text": "done"})
        assert result == "done"

    def test_wait_returns_seconds(self, dispatcher):
        assert dispatcher.dispatch("wait", {"seconds": 3}) == 3
