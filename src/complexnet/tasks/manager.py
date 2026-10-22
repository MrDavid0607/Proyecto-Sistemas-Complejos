"""Task Manager: ciclo de vida de las tareas (creación, despacho, ejecución,
retorno de resultados y reasignación)."""

import threading
import time

from ..communication import TASK_ACK, TASK_RESULT, TASK_SUBMIT, Message
from . import executors
from .task import (
    ASSIGNED,
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    Task,
    TaskFailed,
)

REPUTATION_SUCCESS = 0.05
REPUTATION_FAILURE = -0.20


class TaskManager:

    def __init__(
        self,
        node,
        ack_timeout=5.0,
        exec_timeout=60.0,
        queue_timeout=30.0,
        retry_interval=1.0,
        max_attempts=3,
    ):
        self.node = node
        self.ack_timeout = ack_timeout
        self.exec_timeout = exec_timeout
        self.queue_timeout = queue_timeout
        self.retry_interval = retry_interval
        self.max_attempts = max_attempts

        self.tasks = {}
        self._executing = set()
        self._lock = threading.RLock()
        self._thread = None
        self._running = False

    # ------------------------------------------------------------ ciclo

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="task-monitor"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)

    # ------------------------------------------------- lado del emisor

    def submit(self, task, allow_local=True, wait=True, timeout=None):
        """Crea y despacha una tarea. Con wait=True devuelve su resultado."""
        task.allow_local = allow_local
        with self._lock:
            self.tasks[task.task_id] = task
        self.node.metrics.incr("tasks_submitted")
        self.node.log.event(
            "TASK_CREATED",
            task=task.task_id,
            name=task.name,
            requirements=task.requirements,
        )
        self._dispatch(task)
        if not wait:
            return task
        task.wait(timeout)
        if task.state == COMPLETED:
            return task.result
        if task.state == FAILED:
            raise TaskFailed(task.error)
        raise TimeoutError(f"{task.task_id} no terminó en {timeout}s")

    def _dispatch(self, task):
        node = self.node
        with self._lock:
            if task.is_final:
                return
            task.last_dispatch_try = time.time()
            if task.attempts >= self.max_attempts:
                self._fail(task, f"reintentos agotados ({self.max_attempts})")
                return
            started = time.perf_counter()
            candidates = node.candidates(
                allow_local=task.allow_local, exclude=task.excluded
            )
            best, scores = node.scheduler.select_node(
                candidates, task.cpu_required, task.memory_required
            )
            if best is None:
                if not task.history or task.history[-1] != "QUEUED":
                    node.log.event("TASK_QUEUED", task=task.task_id,
                                   reason="sin candidatos aptos")
                    task.history.append("QUEUED")
                task.state = PENDING
                task.assigned_node = None
                return
            task.attempts += 1
            task.assigned_node = best.node_id
            task.state = ASSIGNED
            task.acked = False
            task.dispatched_at = time.time()
            task.history.append(f"ASSIGNED:{best.node_id}")
            if task.attempts == 1:
                node.metrics.record(
                    "assignment_times", time.perf_counter() - started
                )
            node.log.event(
                "TASK_ASSIGNED",
                task=task.task_id,
                to=best.node_id,
                score=round(scores[best.node_id], 4),
                attempt=task.attempts,
            )
            local = best.node_id == node.node_id
            target = None if local else node.peers.get(best.node_id)

        if local:
            self._execute_local(task)
        elif target is not None:
            node.send(
                TASK_SUBMIT,
                {
                    "task_id": task.task_id,
                    "task_name": task.name,
                    "parameters": task.parameters,
                    "requirements": task.requirements,
                },
                target.address,
            )

    def _execute_local(self, task):
        task.acked = True
        task.state = RUNNING
        threading.Thread(
            target=self._run_local, args=(task,), daemon=True,
            name=f"local-{task.task_id}",
        ).start()

    def _run_local(self, task):
        node = self.node
        node.resources.task_started()
        started = time.perf_counter()
        node.log.event("TASK_RUNNING", task=task.task_id, on=node.node_id)
        try:
            data = executors.execute(task.name, task.parameters)
            elapsed = time.perf_counter() - started
            self._complete(task, node.node_id, data, elapsed)
        except Exception as error:
            node.log.event("TASK_ERROR", task=task.task_id, error=repr(error))
            self._fail(task, f"error de ejecución local: {error}")
        finally:
            node.resources.task_finished()

    def handle_ack(self, message, address):
        with self._lock:
            task = self.tasks.get(message.payload.get("task_id"))
            if (
                task is None
                or task.is_final
                or task.assigned_node != message.sender_id
            ):
                return
            task.acked = True
            if task.state == ASSIGNED:
                task.state = RUNNING
        self.node.log.event(
            "TASK_ACK", task=task.task_id, by=message.sender_id
        )

    def handle_result(self, message, address):
        payload = message.payload
        with self._lock:
            task = self.tasks.get(payload.get("task_id"))
            if task is None or task.is_final:
                return
            status = payload.get("status")
            if status == COMPLETED:
                pass
            elif task.assigned_node != message.sender_id:
                return  # fallo de un intento anterior ya reasignado
        if status == COMPLETED:
            self._complete(
                task,
                message.sender_id,
                payload.get("result_data"),
                payload.get("execution_time_sec", 0.0),
            )
        else:
            self.node.log.event(
                "TASK_ERROR",
                task=task.task_id,
                on=message.sender_id,
                error=payload.get("error"),
            )
            self.reassign(task, f"fallo en {message.sender_id}")

    def _complete(self, task, executor_id, data, execution_time):
        node = self.node
        with self._lock:
            if task.is_final:
                return
            task.state = COMPLETED
            task.result = data
            task.executed_by = executor_id
            task.completed_at = time.time()
            task.history.append(f"COMPLETED:{executor_id}")
        node.metrics.incr("tasks_completed")
        node.metrics.record("execution_times", float(execution_time))
        node.metrics.record("total_times", task.completed_at - task.created_at)
        if task.recovery_started_at is not None:
            node.metrics.record(
                "recovery_times", task.completed_at - task.recovery_started_at
            )
        if executor_id != node.node_id:
            node.peers.adjust_reputation(executor_id, REPUTATION_SUCCESS)
        node.log.event(
            "TASK_COMPLETED",
            task=task.task_id,
            by=executor_id,
            execution_sec=round(float(execution_time), 3),
            total_sec=round(task.completed_at - task.created_at, 3),
            attempts=task.attempts,
        )
        task.finish()

    def _fail(self, task, reason):
        with self._lock:
            if task.is_final:
                return
            task.state = FAILED
            task.error = reason
            task.completed_at = time.time()
            task.history.append("FAILED")
        self.node.metrics.incr("tasks_failed")
        self.node.log.event("TASK_FAILED", task=task.task_id, reason=reason)
        task.finish()

    # ------------------------------------------------ reasignación

    def reassign(self, task, reason):
        """Retira la tarea del nodo actual y la despacha a otro candidato."""
        node = self.node
        with self._lock:
            if task.is_final:
                return
            previous = task.assigned_node
            if previous is not None:
                task.excluded.add(previous)
                if previous != node.node_id:
                    node.peers.adjust_reputation(previous, REPUTATION_FAILURE)
            if task.recovery_started_at is None:
                task.recovery_started_at = time.time()
            task.reassignments += 1
            task.state = PENDING
            task.assigned_node = None
            task.history.append(f"REASSIGN:{previous}")
        node.metrics.incr("tasks_reassigned")
        node.log.event(
            "TASK_REASSIGN", task=task.task_id, from_node=previous, reason=reason
        )
        self._dispatch(task)

    def on_node_failed(self, node_id):
        """Recovery Manager: reasigna las tareas que estaban en un nodo caído."""
        with self._lock:
            affected = [
                t
                for t in self.tasks.values()
                if not t.is_final and t.assigned_node == node_id
            ]
        for task in affected:
            self.reassign(task, f"nodo {node_id} OFFLINE")

    def _monitor_loop(self):
        while self._running:
            now = time.time()
            for task in list(self.tasks.values()):
                if task.is_final:
                    continue
                if task.assigned_node is None:
                    if now - task.created_at > self.queue_timeout:
                        self._fail(task, "sin nodos aptos (tiempo de espera agotado)")
                    elif now - task.last_dispatch_try >= self.retry_interval:
                        self._dispatch(task)
                elif (
                    not task.acked
                    and task.dispatched_at is not None
                    and now - task.dispatched_at > self.ack_timeout
                ):
                    self.reassign(
                        task,
                        f"sin respuesta de {task.assigned_node} en "
                        f"{self.ack_timeout:g}s",
                    )
                elif (
                    task.dispatched_at is not None
                    and now - task.dispatched_at > self.exec_timeout
                ):
                    self.reassign(task, "timeout de ejecución")
            time.sleep(0.25)

    # --------------------------------------------- lado del trabajador

    def handle_submit(self, message, address):
        node = self.node
        payload = message.payload
        task_id = payload["task_id"]
        node.send(TASK_ACK, {"task_id": task_id}, address)
        with self._lock:
            if task_id in self._executing:
                return
            self._executing.add(task_id)
        threading.Thread(
            target=self._work, args=(message.sender_id, payload, address),
            daemon=True, name=f"work-{task_id}",
        ).start()

    def _work(self, requester, payload, address):
        node = self.node
        task_id = payload["task_id"]
        node.resources.task_started()
        node.log.event("TASK_RUNNING", task=task_id, on=node.node_id,
                       requested_by=requester)
        started = time.perf_counter()
        try:
            data = executors.execute(payload["task_name"], payload.get("parameters"))
            reply = {
                "task_id": task_id,
                "status": COMPLETED,
                "execution_time_sec": round(time.perf_counter() - started, 4),
                "result_data": data,
            }
        except Exception as error:
            reply = {
                "task_id": task_id,
                "status": FAILED,
                "execution_time_sec": round(time.perf_counter() - started, 4),
                "error": repr(error),
            }
        finally:
            node.resources.task_finished()
        if node.running:
            node.send(TASK_RESULT, reply, address)
