"""Modelo de tarea y su ciclo de vida."""

import threading
import time
import uuid

PENDING = "PENDING"
ASSIGNED = "ASSIGNED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

FINAL_STATES = (COMPLETED, FAILED)


class TaskFailed(RuntimeError):
    """La tarea terminó en estado FAILED (sin nodos, reintentos agotados...)."""


class Task:
    """Unidad de trabajo que se despacha a la red.

    requirements: {"cpu": CPU libre mínima en %, "memory": memoria libre mínima en MB}
    """

    def __init__(self, name, parameters=None, requirements=None, data=None,
                 task_id=None):
        self.task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        self.name = name
        self.parameters = dict(parameters or {})
        if data is not None:
            self.parameters.setdefault("dataset", data)
        self.requirements = dict(requirements or {})

        self.state = PENDING
        self.assigned_node = None
        self.allow_local = True
        self.attempts = 0
        self.reassignments = 0
        self.excluded = set()
        self.acked = False
        self.history = []

        self.result = None
        self.error = None
        self.executed_by = None

        self.created_at = time.time()
        self.dispatched_at = None
        self.completed_at = None
        self.recovery_started_at = None
        self.last_dispatch_try = 0.0

        self._done = threading.Event()

    @property
    def cpu_required(self):
        return float(self.requirements.get("cpu", 0.0))

    @property
    def memory_required(self):
        return float(self.requirements.get("memory", 0.0))

    @property
    def is_final(self):
        return self.state in FINAL_STATES

    def finish(self):
        self._done.set()

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "state": self.state,
            "assigned_node": self.assigned_node,
            "executed_by": self.executed_by,
            "attempts": self.attempts,
            "reassignments": self.reassignments,
            "result": self.result,
            "error": self.error,
            "history": list(self.history),
        }
