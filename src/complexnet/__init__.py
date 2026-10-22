"""ComplexNet API: computación descentralizada sobre redes Ad hoc."""

from .node import Node, NodeConfig
from .tasks import Task, TaskFailed

__all__ = ["Node", "NodeConfig", "Task", "TaskFailed"]
