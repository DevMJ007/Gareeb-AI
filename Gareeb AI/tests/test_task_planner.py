"""Task planning and execution tests (FR-06, PRD section 12)."""
import time
import pytest
from pathlib import Path

from core.permissions import PermissionManager, PermissionError_
from core.task_planner import (
    TaskPlanner, TaskPlannerError, TaskStatus, StepStatus, KNOWN_ACTIONS,
)
from services.tool_dispatcher import ToolDispatcher
from utils.file_utils import FileUtils


@pytest.fixture
def pm():
    return PermissionManager(config_manager=None)


def ok_dispatcher(action, params):
    """A dispatcher that always succeeds."""
    return {"ok": True, "action": action, "params": params}


def make_planner(pm, dispatcher=ok_dispatcher, **kw):
    return TaskPlanner(permissions=pm, dispatcher=dispatcher, **kw)


# ----------------------------------------------------------------------
# Planning
# ----------------------------------------------------------------------
class TestPlanning:
    def test_plan_basic(self, pm):
        planner = make_planner(pm)
        task = planner.plan("Open notepad", [
            {"action": "open_app", "params": {"app": "notepad"}},
        ])
        assert len(task.steps) == 1
        assert task.steps[0].action == "open_app"
        assert task.status == TaskStatus.PENDING

    def test_plan_rejects_unknown_action(self, pm):
        planner = make_planner(pm)
        with pytest.raises(TaskPlannerError):
            planner.plan("Bad", [{"action": "format_disk", "params": {}}])

    def test_plan_rejects_arbitrary_shell(self, pm):
        planner = make_planner(pm)
        with pytest.raises(TaskPlannerError):
            planner.plan("Evil", [{"action": "run_shell", "params": {"cmd": "rm -rf /"}}])

    def test_empty_plan_is_valid(self, pm):
        planner = make_planner(pm)
        task = planner.plan("Nothing", [])
        assert task.status == TaskStatus.PENDING

    def test_steps_from_json_normalizes(self):
        specs = TaskPlanner.steps_from_json([
            {"tool": "open_app", "parameters": {"app": "notepad"},
             "explain": "Open Notepad"},
            {"action": "respond", "params": {"text": "done"}},
        ])
        assert specs[0]["action"] == "open_app"
        assert specs[0]["params"]["app"] == "notepad"
        assert specs[0]["description"] == "Open Notepad"
        assert specs[1]["action"] == "respond"

    def test_steps_from_json_rejects_garbage(self):
        with pytest.raises(TaskPlannerError):
            TaskPlanner.steps_from_json("not a list")
        with pytest.raises(TaskPlannerError):
            TaskPlanner.steps_from_json(["string instead of dict"])


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
class TestExecution:
    def test_success_path(self, pm):
        planner = make_planner(pm)
        task = planner.plan("Say hi", [
            {"action": "respond", "params": {"text": "hi"}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.COMPLETED
        assert all(s.status == StepStatus.DONE for s in result.steps)
        assert "success" in result.summary.lower()

    def test_failure_stops_remaining_steps(self, pm):
        calls = []

        def dispatcher(action, params):
            calls.append(action)
            if action == "open_app" and params.get("app") == "notepad":
                raise RuntimeError("cannot start")
            return {"ok": True}

        planner = make_planner(pm, dispatcher)
        task = planner.plan("Multi", [
            {"action": "open_app", "params": {"app": "notepad"}},
            {"action": "respond", "params": {"text": "never runs"}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.FAILED
        assert result.steps[0].status == StepStatus.FAILED
        assert result.steps[1].status == StepStatus.SKIPPED
        assert calls == ["open_app"]  # second step never dispatched
        assert "stopped at step 1" in result.summary.lower()

    def test_permission_denied_fails_safely(self, pm):
        planner = make_planner(pm)
        task = planner.plan("Capture", [
            {"action": "capture_screen", "params": {}},  # permission OFF
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.FAILED
        assert "permission" in result.steps[0].error.lower()

    def test_cancellation_before_first_step(self, pm):
        planner = make_planner(pm)
        task = planner.plan("Cancel me", [
            {"action": "respond", "params": {"text": "a"}},
            {"action": "respond", "params": {"text": "b"}},
        ])
        planner.cancel()
        result = planner.execute(task)
        assert result.status == TaskStatus.CANCELLED
        assert result.steps[0].status == StepStatus.CANCELLED

    def test_cancel_during_execution(self, pm):
        planner_holder = {}

        def dispatcher(action, params):
            # Cancel from "inside" the first step.
            planner_holder["planner"].cancel()
            return {"ok": True}

        planner = make_planner(pm, dispatcher)
        planner_holder["planner"] = planner
        task = planner.plan("Cancel during", [
            {"action": "open_app", "params": {"app": "notepad"}},
            {"action": "respond", "params": {"text": "b"}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.CANCELLED
        # First step ran (already started), second was cancelled.
        assert result.steps[1].status == StepStatus.CANCELLED
        assert "cancelled" in result.summary.lower()

    def test_execution_time_limit(self, pm):
        def slow_dispatcher(action, params):
            time.sleep(0.3)
            return {"ok": True}

        planner = make_planner(pm, slow_dispatcher, max_execution_time=1)
        task = planner.plan("Slow", [
            {"action": "open_app", "params": {"app": "notepad"}}
            for _ in range(10)
        ])
        result = planner.execute(task)
        assert result.status in (TaskStatus.FAILED, TaskStatus.CANCELLED)
        assert "time limit" in result.summary.lower()

    def test_verify_file_exists_success(self, pm, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("data", encoding="utf-8")

        planner = make_planner(pm)
        task = planner.plan("Verify", [
            {"action": "respond", "params": {"text": "x"},
             "verify": {"type": "file_exists", "path": str(target)}},
        ])
        assert planner.execute(task).status == TaskStatus.COMPLETED

    def test_verify_file_exists_failure(self, pm, tmp_path):
        missing = tmp_path / "nope.txt"
        planner = make_planner(pm)
        task = planner.plan("Verify fail", [
            {"action": "respond", "params": {"text": "x"},
             "verify": {"type": "file_exists", "path": str(missing)}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.FAILED
        assert "verification failed" in result.steps[0].error.lower()

    def test_no_dispatcher_fails_clearly(self, pm):
        planner = TaskPlanner(permissions=pm, dispatcher=None)
        task = planner.plan("No tools", [
            {"action": "capture_screen", "params": {}},
        ])
        # Screen permission is off anyway; either way it must not crash.
        result = planner.execute(task)
        assert result.status == TaskStatus.FAILED


# ----------------------------------------------------------------------
# Confirmation integration
# ----------------------------------------------------------------------
class TestConfirmationIntegration:
    def test_sensitive_action_approved(self, pm, tmp_path):
        dispatcher = ToolDispatcher(file_utils=FileUtils()).dispatch
        planner = make_planner(pm, dispatcher)
        planner.set_confirmation_handler(
            lambda cid, a, d: planner.resolve_confirmation(cid, True))

        target = tmp_path / "move_me.txt"
        target.write_text("x", encoding="utf-8")
        dest = tmp_path / "moved.txt"

        task = planner.plan("Move file", [
            {"action": "move_file",
             "params": {"src_path": str(target), "dst_path": str(dest)}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.COMPLETED
        assert dest.exists()

    def test_sensitive_action_denied(self, pm, tmp_path):
        dispatcher = ToolDispatcher(file_utils=FileUtils()).dispatch
        planner = make_planner(pm, dispatcher)
        planner.set_confirmation_handler(
            lambda cid, a, d: planner.resolve_confirmation(cid, False))

        target = tmp_path / "keep_me.txt"
        target.write_text("x", encoding="utf-8")
        dest = tmp_path / "nope.txt"

        task = planner.plan("Move file", [
            {"action": "move_file",
             "params": {"src_path": str(target), "dst_path": str(dest)}},
        ])
        result = planner.execute(task)
        assert result.status == TaskStatus.FAILED
        assert "declined" in result.steps[0].error.lower()
        assert target.exists() and not dest.exists()


# ----------------------------------------------------------------------
# Progress reporting
# ----------------------------------------------------------------------
class TestProgress:
    def test_progress_callback_receives_events(self, pm):
        events = []
        planner = make_planner(pm, progress_callback=events.append)
        task = planner.plan("Progress", [
            {"action": "respond", "params": {"text": "1"}},
            {"action": "respond", "params": {"text": "2"}},
        ])
        planner.execute(task)
        kinds = {e["event"] for e in events}
        assert "task_started" in kinds
        assert "step_update" in kinds
        assert "task_finished" in kinds

    def test_progress_value(self, pm):
        planner = make_planner(pm)
        task = planner.plan("P", [
            {"action": "respond", "params": {"text": "a"}},
            {"action": "respond", "params": {"text": "b"}},
        ])
        assert task.progress == 0.0
        planner.execute(task)
        assert task.progress == 1.0
