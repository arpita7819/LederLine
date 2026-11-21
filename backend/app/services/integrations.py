from typing import Optional

from sqlmodel import Session

from ..adapters import GitHubTracker, MockTracker, TrackerAdapter
from ..config import settings
from ..models import AuditLog, Setting


def build_adapters() -> dict[str, TrackerAdapter]:
    """Register new trackers here (Linear, Jira...)."""
    return {a.name: a for a in (MockTracker(), GitHubTracker(settings.github_token, settings.github_repo))}


def active_name(session: Session) -> str:
    row = session.get(Setting, "tracker")
    return row.value if row and row.value else "mock"


def get_active(session: Session, adapters: Optional[dict] = None) -> TrackerAdapter:
    adapters = adapters or build_adapters()
    return adapters.get(active_name(session)) or adapters["mock"]


def set_active(session: Session, name: str, actor: str = "local-user",
               adapters: Optional[dict] = None) -> None:
    adapters = adapters or build_adapters()
    if name not in adapters:
        raise ValueError(f"Unknown tracker “{name}”")
    if not adapters[name].is_configured():
        raise ValueError(f"{adapters[name].label} is not configured. {adapters[name].description}")
    before = active_name(session)
    session.merge(Setting(key="tracker", value=name))
    session.add(AuditLog(actor=actor, action="tracker.select", entity_type="setting",
                         before={"tracker": before}, after={"tracker": name}))
    session.commit()


def describe(session: Session) -> list[dict]:
    cur = active_name(session)
    return [{"name": a.name, "label": a.label, "description": a.description,
             "configured": a.is_configured(), "active": a.name == cur}
            for a in build_adapters().values()]
