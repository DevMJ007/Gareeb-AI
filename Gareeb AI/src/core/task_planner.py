#!/usr/bin/env python3
"""
Multi-step task execution engine for MJ AI (FR-06).

Plans a request into discrete steps, validates each step through the
permission layer, executes them with progress tracking, supports
cancellation, and records outcomes.
"""

from __future__ import annotations

import time
import logging
import threading
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

from core.permissions import PermissionManager, Permission, PermissionError_


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Step:
    """A single task step."""
    id: int
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    error: str = ""
    result: Any = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    verify: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "status": self.status.value,
            "error": self.error,
            "result": self.result,
            "verify": self.verify,
        }


@dataclass
class Task:
    """A complete multi-step task."""
    id: str
    description: str
    steps: List[Step] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    current_step: int = 0
    summary: str = ""

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps
                   if s.status in (StepStatus.DONE, StepStatus.SKIPPED))
        return done / len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "progress": round(self.progress, 3),
            "current_step": self.current_step,
            "steps": [s.to_dict() for s in self.steps],
            "summary": self.summary,
        }


# Actions the planner understands in v1 (limited, reliable set).
KNOWN_ACTIONS = {
    "open_app", "search_web", "switch_window", "minimize_window", "maximize_window",
    "type_text", "press_key", "capture_screen", "read_screen",
    "create_file", "read_file", "create_folder", "move_file", "copy_file",
    "rename_file", "search_files", "wait", "respond",
}

# Maps action -> permission required.
ACTION_PERMISSIONS: Dict[str, Permission] = {
    "open_app": Permission.OPEN_APPLICATION,
    "search_web": Permission.OPEN_APPLICATION,
    "switch_window": Permission.SWITCH_WINDOW,
    "minimize_window": Permission.WINDOW_MANAGE,
    "maximize_window": Permission.WINDOW_MANAGE,
    "type_text": Permission.TYPE_TEXT,
    "press_key": Permission.TYPE_TEXT,
    "capture_screen": Permission.CAPTURE_SCREEN,
    "read_screen": Permission.READ_SCREEN,
    "create_file": Permission.CREATE_FILE,
    "read_file": Permission.READ_FILE,
    "create_folder": Permission.CREATE_FOLDER,
    "move_file": Permission.MOVE_FILE,
    "copy_file": Permission.COPY_FILE,
    "rename_file": Permission.RENAME_FILE,
    "search_files": Permission.SEARCH_FILES,
    "wait": Permission.CHAT,
    "respond": Permission.CHAT,
}


class TaskCancelled(Exception):
    """Raised when the user cancels a running task."""


class TaskPlannerError(Exception):
    """Raised for planning/execution failures."""


class TaskPlanner:
    """
    Plans and executes supported multi-step workflows.

    The planner does not attempt unrestricted autonomy: only known, tested
    actions in KNOWN_ACTIONS are executed. Anything else fails safely with a
    clear explanation.
    """

    def __init__(self,
                 permissions: PermissionManager,
                 dispatcher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
                 memory_store=None,
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 max_execution_time: int = 30):
        self.logger = logging.getLogger(__name__)
        self.permissions = permissions
        self.dispatcher = dispatcher
        self.memory_store = memory_store
        self.progress_callback = progress_callback
        self.max_execution_time = max_execution_time

        self._cancel = threading.Event()
        self._current_task: Optional[Task] = None
        self._task_counter = 0
        self._lock = threading.Lock()

        # Register the confirmation prompt passthrough so that permission
        # requests reach the UI.
        self.permissions.confirmation_prompt = self._on_confirmation_prompt
        self._ui_confirmation_handler: Optional[Callable[[str, str, str], None]] = None

    # ------------------------------------------------------------------
    # Confirmation bridging
    # ------------------------------------------------------------------
    def set_confirmation_handler(self, handler: Callable[[str, str, str], None]) -> None:
        self._ui_confirmation_handler = handler

    def _on_confirmation_prompt(self, conf_id: str, action: str, description: str) -> None:
        if self._ui_confirmation_handler:
            self._ui_confirmation_handler(conf_id, action, description)

    def resolve_confirmation(self, conf_id: str, approved: bool) -> bool:
        return self.permissions.resolve_confirmation(conf_id, approved)

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    def plan(self, description: str,
             steps_spec: Optional[List[Dict[str, Any]]] = None) -> Task:
        """
        Build a Task from an explicit step list.

        steps_spec: [{"action": "open_app", "params": {...}}, ...]

        Each step is validated during execution, not only at plan time, so a
        change in system state cannot bypass checks.
        """
        with self._lock:
            # A cancellation requested for a previous task must not leak into
            # this one. A cancellation after planning must remain in effect.
            if self._current_task is None:
                self._cancel.clear()
            self._task_counter += 1
            task_id = f"task-{self._task_counter}"

        steps: List[Step] = []
        for i, spec in enumerate(steps_spec or []):
            action = str(spec.get("action", "")).strip()
            params = dict(spec.get("params", {}) or {})
            description_text = str(spec.get("description", "") or action)

            if action not in KNOWN_ACTIONS:
                raise TaskPlannerError(
                    f"Unsupported action '{action}'. Version 1.0 supports: "
                    f"{', '.join(sorted(KNOWN_ACTIONS))}."
                )

            steps.append(Step(
                id=i + 1,
                action=action,
                params=params,
                description=description_text,
                verify=spec.get("verify"),
            ))

        task = Task(id=task_id, description=description, steps=steps)
        self.logger.info(f"Planned task {task_id} with {len(steps)} step(s)")
        return task

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def cancel(self) -> bool:
        """Request cancellation of the running task."""
        self._cancel.set()
        self.logger.info("Task cancellation requested")
        return True

    def reset(self) -> None:
        self._cancel.clear()

    @property
    def is_running(self) -> bool:
        return self._current_task is not None and not self._cancel.is_set()

    @property
    def current_task(self) -> Optional[Task]:
        return self._current_task

    def execute(self, task: Task) -> Task:
        """
        Execute a planned task step by step.

        Validation happens per step; a failing step stops the task safely and
        reports the final state truthfully.
        """
        self._current_task = task
        task.status = TaskStatus.RUNNING
        started = time.time()
        self._emit(task, "task_started")

        try:
            for idx, step in enumerate(task.steps):
                task.current_step = idx

                # Cancellation check before each step.
                if self._cancel.is_set():
                    for remaining in task.steps[idx:]:
                        remaining.status = StepStatus.CANCELLED
                        remaining.error = "Cancelled by user."
                    task.status = TaskStatus.CANCELLED
                    task.summary = self._final_summary(task)
                    self._finish(task)
                    return task

                # Global execution time budget.
                if time.time() - started > self.max_execution_time:
                    step.status = StepStatus.FAILED
                    step.error = "Execution time limit reached."
                    task.status = TaskStatus.FAILED
                    task.summary = self._final_summary(task)
                    self._finish(task)
                    return task

                self._run_step(step)
                self._emit(task, "step_finished")

                if self._cancel.is_set() or step.status == StepStatus.CANCELLED:
                    for remaining in task.steps[idx + 1:]:
                        remaining.status = StepStatus.CANCELLED
                        remaining.error = "Cancelled by user."
                    task.status = TaskStatus.CANCELLED
                    task.summary = self._final_summary(task)
                    self._finish(task)
                    return task

                if step.status == StepStatus.FAILED:
                    # Stop safely: skip remaining steps, keep state honest.
                    for remaining in task.steps[idx + 1:]:
                        remaining.status = StepStatus.SKIPPED
                        remaining.error = "Skipped due to earlier failure."
                    task.status = TaskStatus.FAILED
                    break

            else:
                task.status = TaskStatus.COMPLETED

            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.COMPLETED

        except Exception as exc:  # unexpected engine failure
            self.logger.error(f"Task engine error: {exc}")
            task.status = TaskStatus.FAILED
            task.summary = f"Task failed: {exc}"

        task.finished_at = time.time()
        if not task.summary:
            task.summary = self._final_summary(task)

        self._finish(task)
        return task

    def _run_step(self, step: Step) -> None:
        step.status = StepStatus.RUNNING
        step.started_at = time.time()
        self._emit_step_update(step)

        try:
            # 1. Permission gate.
            permission = ACTION_PERMISSIONS[step.action]
            context = dict(step.params)
            context.setdefault("description", step.description)
            self.permissions.authorize(permission, context)

            # 2. Cancellation re-check after any blocking confirmation.
            if self._cancel.is_set():
                step.status = StepStatus.CANCELLED
                step.finished_at = time.time()
                return

            # 3. Dispatch to tool layer.
            if step.action == "wait":
                seconds = float(step.params.get("seconds", 0))
                if seconds < 0 or seconds > 10:
                    raise TaskPlannerError("Wait duration must be between 0 and 10 seconds.")
                deadline = time.monotonic() + seconds
                while True:
                    if self._cancel.is_set():
                        raise TaskCancelled("Task cancelled while waiting.")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.1, remaining))
                step.result = {"waited_seconds": seconds}
            elif step.action == "respond":
                step.result = step.params.get("text", "")
            elif self.dispatcher is None:
                raise TaskPlannerError("No tool dispatcher configured.")
            else:
                step.result = self.dispatcher(step.action, step.params)

            # 4. Verification when possible - never claim success blindly.
            if step.verify:
                self._verify_step(step)

            step.status = StepStatus.DONE

        except PermissionError_ as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            self.logger.warning(f"Step {step.id} denied: {exc}")
        except TaskCancelled:
            step.status = StepStatus.CANCELLED
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            self.logger.error(f"Step {step.id} failed: {exc}")
        finally:
            step.finished_at = time.time()
            self._emit_step_update(step)

    def _verify_step(self, step: Step) -> None:
        """Verify a step result using the supplied expectation."""
        verify = step.verify or {}
        kind = verify.get("type")

        if kind == "file_exists":
            from pathlib import Path
            path = verify.get("path") or step.params.get("path") or step.params.get("file_path")
            if not path:
                raise TaskPlannerError("Verification error: no path supplied.")
            exists = Path(path).exists()
            if not exists:
                raise TaskPlannerError(
                    f"Verification failed: expected file '{path}' was not created."
                )
            step.result = {"verified": True, "path": str(path)}

        elif kind == "folder_exists":
            from pathlib import Path
            path = verify.get("path")
            if not path or not Path(path).is_dir():
                raise TaskPlannerError(
                    f"Verification failed: expected folder '{path}' was not created."
                )
            step.result = {"verified": True, "path": str(path)}

        elif kind == "app_running":
            ok = bool(step.result)
            if not ok:
                raise TaskPlannerError("Verification failed: application did not start.")

        else:
            self.logger.warning(f"Unknown verification type: {kind}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _finish(self, task: Task) -> None:
        if task.finished_at is None:
            task.finished_at = time.time()
        self._emit(task, "task_finished")

        if self.memory_store is not None:
            try:
                self.memory_store.record_task(
                    description=task.description,
                    status=task.status.value,
                    steps=[s.to_dict() for s in task.steps],
                    finished=True,
                )
            except Exception as exc:
                self.logger.warning(f"Could not record task history: {exc}")

        self._current_task = None

    @staticmethod
    def _final_summary(task: Task) -> str:
        done = sum(1 for s in task.steps if s.status == StepStatus.DONE)
        total = len(task.steps)
        failed = next((s for s in task.steps if s.status == StepStatus.FAILED), None)

        if task.status == TaskStatus.COMPLETED:
            return f"All {total} step(s) completed successfully."
        if task.status == TaskStatus.CANCELLED:
            return f"Cancelled after {done} of {total} step(s)."
        if failed is not None:
            reason = failed.error or "unknown error"
            return (f"Stopped at step {failed.id} ({failed.description}): {reason}. "
                    f"{done} of {total} step(s) completed.")
        return f"Task ended with status '{task.status.value}'."

    def _emit(self, task: Task, event: str) -> None:
        if self.progress_callback is None:
            return
        try:
            payload = {"event": event, "task": task.to_dict()}
            self.progress_callback(payload)
        except Exception as exc:
            self.logger.debug(f"Progress callback error: {exc}")

    def _emit_step_update(self, step: Step) -> None:
        if self._current_task is None or self.progress_callback is None:
            return
        try:
            self.progress_callback({
                "event": "step_update",
                "task": self._current_task.to_dict(),
                "step": step.to_dict(),
            })
        except Exception as exc:
            self.logger.debug(f"Progress callback error: {exc}")

    # ------------------------------------------------------------------
    # Convenience for the AI layer: parse model-produced step lists
    # ------------------------------------------------------------------
    @staticmethod
    def steps_from_json(steps_json: Any) -> List[Dict[str, Any]]:
        """Normalize a model-provided step list into planner specs."""
        if isinstance(steps_json, list):
            raw = steps_json
        elif isinstance(steps_json, dict):
            raw = steps_json.get("steps", [])
        else:
            raise TaskPlannerError("Steps must be a list or object with 'steps'.")

        specs = []
        for item in raw:
            if not isinstance(item, dict):
                raise TaskPlannerError("Each step must be an object.")
            action = item.get("action") or item.get("tool") or ""
            params = item.get("params") or item.get("parameters") or {}
            desc = item.get("description") or item.get("explain") or action
            spec = {"action": action, "params": params, "description": desc}
            if item.get("verify"):
                spec["verify"] = item["verify"]
            specs.append(spec)
        return specs
