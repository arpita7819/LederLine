from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    meeting_date: date
    attendees: list = Field(default_factory=list, sa_column=Column(JSON))
    raw_text: str
    source_format: str = "txt"  # txt | vtt | srt
    status: str = "ingested"  # ingested | extracting | extracted | failed
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=now)


class Speaker(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", index=True)
    label: str  # original label from the transcript
    display_name: str
    merged_into_id: Optional[int] = Field(default=None, foreign_key="speaker.id")


class Utterance(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", index=True)
    speaker_id: int = Field(foreign_key="speaker.id")
    idx: int
    timestamp: Optional[float] = None  # seconds from start
    text: str


class Person(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: Optional[str] = None


class Decision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", index=True)
    text: str
    quote: str
    speaker_id: Optional[int] = Field(default=None, foreign_key="speaker.id")
    timestamp: Optional[float] = None
    confidence: float = 0.0
    status: str = "active"  # active | superseded | contested
    superseded_by_id: Optional[int] = Field(default=None, foreign_key="decision.id")
    review_status: str = "pending"  # pending | approved | rejected
    keywords: list = Field(default_factory=list, sa_column=Column(JSON))
    embedding: Optional[list] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now)


class ConflictCheck(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    new_decision_id: int = Field(foreign_key="decision.id", index=True)
    old_decision_id: int = Field(foreign_key="decision.id", index=True)
    verdict: str  # consistent | contradicts | supersedes | unrelated
    rationale: str = ""
    resolution: str = "pending"  # pending | supersede_old | keep_old | exception
    created_at: datetime = Field(default_factory=now)


class ActionItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", index=True)
    title: str
    quote: str
    speaker_id: Optional[int] = Field(default=None, foreign_key="speaker.id")
    timestamp: Optional[float] = None
    confidence: float = 0.0
    owner_id: Optional[int] = Field(default=None, foreign_key="person.id")
    deadline: Optional[datetime] = None
    needs_clarification: bool = False
    review_status: str = "pending"  # pending | approved | rejected
    tracker: Optional[str] = None
    tracker_ref: Optional[str] = None
    task_status: str = "todo"  # todo | in_progress | done


class Reminder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    action_item_id: int = Field(foreign_key="actionitem.id", index=True)
    offset: str  # 3d | 1d | 2h
    fire_at: datetime
    sent_at: Optional[datetime] = None
    read: bool = False
    message: str = ""


class Digest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", index=True)
    week_start: date
    structured: dict = Field(default_factory=dict, sa_column=Column(JSON))
    summary_text: str = ""
    created_at: datetime = Field(default_factory=now)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor: str = "local-user"
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    before: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    after: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""
