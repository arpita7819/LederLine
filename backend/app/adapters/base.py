"""Tracker adapter interface. To add Linear or Jira: subclass TrackerAdapter and register it
in services/integrations.py (build_adapters). Nothing else changes."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


class TrackerError(RuntimeError):
    """Raised when a tracker cannot create or update a task. The message is shown to the user."""


@dataclass
class TaskPayload:
    item_id: int
    title: str
    owner: Optional[str]
    deadline: Optional[datetime]
    meeting_title: str
    meeting_date: date
    quote: str

    def description(self) -> str:
        due = self.deadline.strftime("%d %b %Y") if self.deadline else "not set"
        return (f"**Owner:** {self.owner or 'unassigned'}\n**Due:** {due}\n\n"
                f"From the meeting “{self.meeting_title}” on {self.meeting_date.isoformat()}.\n\n"
                f"> {self.quote}\n\nCreated by Ledgerline after human review.")


class TrackerAdapter(ABC):
    name: str = ""
    label: str = ""
    description: str = ""

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def create_task(self, task: TaskPayload) -> str:
        """Create the task and return its reference (stored as ActionItem.tracker_ref)."""

    @abstractmethod
    def update_status(self, ref: str, status: str) -> None:
        """status is one of todo | in_progress | done."""
