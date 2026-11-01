"""File utility safety tests (FR-07, PRD section 12)."""
import os
import pytest
from pathlib import Path

from utils.file_utils import FileUtils, FileValidationError


@pytest.fixture
def fu():
    return FileUtils(config_manager=None)


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


# ----------------------------------------------------------------------
# Reading & writing
# ----------------------------------------------------------------------
class TestReadWrite:
    def test_write_and_read(self, fu, work_dir):
        path = work_dir / "note.txt"
        fu.safe_write_file(str(path), "Hello MJ")
        assert fu.safe_read_file(str(path)) == "Hello MJ"

    def test_write_creates_parents(self, fu, work_dir):
        path = work_dir / "a" / "b" / "c.txt"
        fu.safe_write_file(str(path), "deep")
        assert path.exists()

    def test_write_without_dirs_fails(self, fu, work_dir):
        path = work_dir / "missing" / "x.txt"
        with pytest.raises(FileValidationError):
            fu.safe_write_file(str(path), "x", create_dirs=False)

    def test_read_missing_file_fails(self, fu, work_dir):
        with pytest.raises(FileValidationError):
            fu.safe_read_file(str(work_dir / "absent.txt"))

    def test_oversized_file_rejected(self, fu, work_dir):
        big = work_dir / "big.txt"
        big.write_text("A" * (2 * 1024 * 1024), encoding="utf-8")  # 2 MB
        with pytest.raises(FileValidationError):
            fu.safe_read_file(str(big), max_size_mb=1)

    def test_backup_existing(self, fu, work_dir):
        path = work_dir / "b.txt"
        path.write_text("old", encoding="utf-8")
        fu.safe_write_file(str(path), "new", backup_existing=True)
        assert path.read_text(encoding="utf-8") == "new"
        backups = list(work_dir.glob("b.backup*.txt"))
        assert backups and backups[0].read_text(encoding="utf-8") == "old"


# ----------------------------------------------------------------------
# Path validation
# ----------------------------------------------------------------------
class TestValidation:
    def test_system_path_rejected(self, fu):
        with pytest.raises(FileValidationError):
            fu.validate_path(r"C:\Windows\System32\cmd.exe")

    def test_traversal_rejected(self, fu, work_dir):
        with pytest.raises(FileValidationError):
            fu.validate_path(str(work_dir / ".." / ".." / "evil.txt"))

    def test_empty_rejected(self, fu):
        with pytest.raises(FileValidationError):
            fu.validate_path("")

    def test_require_exists(self, fu, work_dir):
        with pytest.raises(FileValidationError):
            fu.validate_path(str(work_dir / "no.txt"), require_exists=True)

    def test_require_dir(self, fu, work_dir):
        f = work_dir / "f.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(FileValidationError):
            fu.validate_path(str(f), require_dir=True)


# ----------------------------------------------------------------------
# Directories & deletion
# ----------------------------------------------------------------------
class TestDirectoryOps:
    def test_create_directory(self, fu, work_dir):
        target = work_dir / "newdir"
        assert fu.safe_create_directory(str(target))
        assert target.is_dir()

    def test_create_nested_directory(self, fu, work_dir):
        target = work_dir / "a" / "b" / "c"
        assert fu.safe_create_directory(str(target))
        assert target.is_dir()

    def test_delete_requires_existence(self, fu, work_dir):
        with pytest.raises(FileValidationError):
            fu.safe_delete_file(str(work_dir / "ghost.txt"), confirm=False)

    def test_delete_happy_path(self, fu, work_dir):
        f = work_dir / "temp.txt"
        f.write_text("x", encoding="utf-8")
        assert fu.safe_delete_file(str(f), confirm=False)
        assert not f.exists()


# ----------------------------------------------------------------------
# Move / copy / rename
# ----------------------------------------------------------------------
class TestMoveCopy:
    def test_copy_file(self, fu, work_dir):
        src = work_dir / "src.txt"
        src.write_text("payload", encoding="utf-8")
        dst = work_dir / "dst.txt"
        assert fu.safe_copy_file(str(src), str(dst))
        assert dst.read_text(encoding="utf-8") == "payload"
        assert src.exists()

    def test_copy_no_overwrite_by_default(self, fu, work_dir):
        src = work_dir / "s.txt"
        src.write_text("x", encoding="utf-8")
        dst = work_dir / "d.txt"
        dst.write_text("existing", encoding="utf-8")
        with pytest.raises(FileValidationError):
            fu.safe_copy_file(str(src), str(dst), overwrite=False)
        assert dst.read_text(encoding="utf-8") == "existing"

    def test_move_file(self, fu, work_dir):
        src = work_dir / "m1.txt"
        src.write_text("data", encoding="utf-8")
        dst = work_dir / "m2.txt"
        assert fu.safe_move_file(str(src), str(dst), confirm=False)
        assert dst.exists() and not src.exists()

    def test_move_no_overwrite_silent_cancel(self, fu, work_dir):
        src = work_dir / "a.txt"
        src.write_text("a", encoding="utf-8")
        dst = work_dir / "b.txt"
        dst.write_text("b", encoding="utf-8")
        # overwrite=False -> refuses without prompting
        with pytest.raises(FileValidationError):
            fu.safe_move_file(str(src), str(dst), overwrite=False, confirm=False)
        assert dst.read_text(encoding="utf-8") == "b"


# ----------------------------------------------------------------------
# Listing & searching
# ----------------------------------------------------------------------
class TestListSearch:
    def test_list_directory(self, fu, work_dir):
        (work_dir / "one.txt").write_text("1", encoding="utf-8")
        (work_dir / "two.txt").write_text("2", encoding="utf-8")
        items = fu.list_directory(str(work_dir))
        names = [i["name"] for i in items]
        assert "one.txt" in names and "two.txt" in names

    def test_list_hides_hidden(self, fu, work_dir):
        (work_dir / ".secret").write_text("x", encoding="utf-8")
        (work_dir / "normal.txt").write_text("x", encoding="utf-8")
        names = [i["name"] for i in fu.list_directory(str(work_dir))]
        assert ".secret" not in names
        names_all = [i["name"] for i in fu.list_directory(str(work_dir),
                                                          include_hidden=True)]
        assert ".secret" in names_all

    def test_search_finds_matches(self, fu, work_dir):
        (work_dir / "a.txt").write_text("hello world", encoding="utf-8")
        (work_dir / "b.txt").write_text("nothing here", encoding="utf-8")
        results = fu.search_in_directory(str(work_dir), "hello")
        assert len(results) == 1
        assert results[0]["file_name"] == "a.txt"
        assert results[0]["total_matches"] >= 1

    def test_search_respects_extension_filter(self, fu, work_dir):
        (work_dir / "a.txt").write_text("needle", encoding="utf-8")
        (work_dir / "b.log").write_text("needle", encoding="utf-8")
        results = fu.search_in_directory(str(work_dir), "needle",
                                         file_extensions=[".txt"])
        assert len(results) == 1
        assert results[0]["file_name"] == "a.txt"

    def test_get_file_info(self, fu, work_dir):
        f = work_dir / "info.txt"
        f.write_text("12345", encoding="utf-8")
        info = fu.get_file_info(str(f))
        assert info["exists"] is True
        assert info["size"] == 5
        assert info["name"] == "info.txt"

    def test_get_file_info_missing(self, fu, work_dir):
        info = fu.get_file_info(str(work_dir / "gone.txt"))
        assert info["exists"] is False


# ----------------------------------------------------------------------
# Sensitive files
# ----------------------------------------------------------------------
class TestSensitiveFiles:
    def test_password_file_not_readable(self, fu, work_dir):
        (work_dir / "passwords.txt").write_text("secret", encoding="utf-8")
        with pytest.raises(FileValidationError):
            fu.safe_read_file(str(work_dir / "passwords.txt"))

    def test_private_key_not_readable(self, fu, work_dir):
        (work_dir / "id_rsa").write_text("key", encoding="utf-8")
        with pytest.raises(FileValidationError):
            fu.safe_read_file(str(work_dir / "id_rsa"))
