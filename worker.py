from PySide6.QtCore import QObject, Signal, Slot


class AIWorker(QObject):
    """Runs one complete user request outside the UI thread."""

    finished = Signal(object)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    @Slot()
    def run(self):
        try:
            print("[WORKER] TASK START")
            result = self.task(self.status.emit)
            print("[WORKER] TASK FINISHED")
            self.finished.emit(result)
            print("[WORKER] FINISHED EMITTED")
        except Exception as error:
            print("[WORKER ERROR]", repr(error))
            self.failed.emit(str(error))