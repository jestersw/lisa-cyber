"""Import all models so Alembic's target_metadata sees them."""

from app.models.models import (
    ActivityEvent,
    Agent,
    AgentActivity,
    ApplicationTemplate,
    BehaviorTemplate,
    Role,
)

__all__ = [
    "ActivityEvent",
    "Agent",
    "AgentActivity",
    "ApplicationTemplate",
    "BehaviorTemplate",
    "Role",
]
