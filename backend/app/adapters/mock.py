from .base import TaskPayload, TrackerAdapter


class MockTracker(TrackerAdapter):
    """Built-in tracker. Tasks live in Ledgerline's own database and show on the Kanban board."""
    name = "mock"
    label = "Mock Tracker (Kanban)"
    description = "The built-in Kanban board. No setup needed."

    def is_configured(self) -> bool:
        return True

    def create_task(self, task: TaskPayload) -> str:
        return f"LL-{task.item_id}"

    def update_status(self, ref: str, status: str) -> None:
        return None  # the board reads status straight from the database
