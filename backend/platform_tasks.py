"""Small durable task receipts for explicit and periodic source checks."""
from functools import wraps
import os
import time
import uuid

from .platform_io import read_json, write_json


def tracked(label):
    def decorate(function):
        @wraps(function)
        def run(self, *args, **kwargs):
            platform = getattr(self, "platform", self)
            task = {"id": uuid.uuid4().hex, "label": label, "pid": os.getpid(), "status": "running", "created_at": time.time()}
            path = platform.root / "tasks" / (task["id"] + ".json")
            write_json(path, task)
            try:
                result = function(self, *args, **kwargs)
                task.update(status="completed", finished_at=time.time())
                if isinstance(result, dict) and result.get("kind") == "addons":
                    task["plan_id"] = result["id"]
                write_json(path, task)
                return result
            except Exception as exc:
                task.update(status="failed", message=str(exc), finished_at=time.time())
                write_json(path, task)
                raise
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
