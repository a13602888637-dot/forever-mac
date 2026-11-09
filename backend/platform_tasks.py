"""Small durable task receipts for explicit and periodic source checks."""
from functools import wraps
from contextvars import ContextVar
import os
import time
import uuid

from .platform_io import read_json, write_json

_current_task = ContextVar("forever_current_task", default=None)


def task_progress(stage, **details):
    """Publish observed stages/byte counts, never a simulated percentage."""
    current = _current_task.get()
    if current is None:
        return
    path, task = current
    task.update(stage=stage, updated_at=time.time(), **details)
    write_json(path, task)


def tracked(label):
    def decorate(function):
        @wraps(function)
        def run(self, *args, **kwargs):
            platform = getattr(self, "platform", self)
            task = {"id": uuid.uuid4().hex, "label": label, "pid": os.getpid(), "status": "running", "created_at": time.time()}
            path = platform.root / "tasks" / (task["id"] + ".json")
            write_json(path, task)
            token = _current_task.set((path, task))
            try:
                result = function(self, *args, **kwargs)
                failed = isinstance(result, dict) and result.get("status") == "failed"
                task.update(status="failed" if failed else "completed", finished_at=time.time())
                if isinstance(result, dict) and result.get("kind") in ("addons", "management"):
                    task["plan_id"] = result["id"]
                    task["plan_kind"] = result["kind"]
                write_json(path, task)
                return result
            except BaseException as exc:
                task.update(status="failed" if isinstance(exc, Exception) else "interrupted",
                            message=str(exc), finished_at=time.time())
                write_json(path, task)
                raise
            finally:
                _current_task.reset(token)
        return run
    return decorate


def task_receipts(root):
    result = []
    for path in (root / "tasks").glob("*.json"):
        task = read_json(path)
        if task["status"] == "running":
            try:
                os.kill(task["pid"], 0)
            except ProcessLookupError:
                task["status"] = "interrupted"
        result.append(task)
    return sorted(result, key=lambda t: t["created_at"], reverse=True)[:20]
