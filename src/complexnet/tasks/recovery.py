"""Recovery Manager: conecta el Failure Detector con la reasignación de tareas."""


class RecoveryManager:

    def __init__(self, task_manager, detector):
        self.task_manager = task_manager
        detector.subscribe(self.on_node_failed)

    def on_node_failed(self, node_id):
        self.task_manager.on_node_failed(node_id)
