from PySide6.QtCore import QObject, Signal, Slot


class AIWorker(QObject):
    """Runs one complete user request outside the UI thread."""

    finished = Signal(str)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    @Slot()
    def run(self):
        try:
            result = self.task(self.status.emit)
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(str(error))