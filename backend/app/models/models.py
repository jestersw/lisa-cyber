"""Domain models (SQLAlchemy 2.0 typed style).

Ported from the original backend. Windows dropped (Linux/macOS only). The
build/deploy/servers tables are left for a later feat/deploy branch.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(String(50), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    agents: Mapped[list[Agent]] = relationship(back_populates="role")
    behavior_templates: Mapped[list[BehaviorTemplate]] = relationship(back_populates="role")


class ApplicationTemplate(Base):
    __tablename__ = "applications_template"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(150), default=None)
    category: Mapped[str | None] = mapped_column(String(50), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    author: Mapped[str | None] = mapped_column(String(100), default=None)
    template_config: Mapped[dict] = mapped_column(JSON)
    os_type: Mapped[str] = mapped_column(String(20), default="linux")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )


class BehaviorTemplate(Base):
    __tablename__ = "behavior_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    os_type: Mapped[str] = mapped_column(String(20), default="linux")
    template_data: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"), default=None)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    agents: Mapped[list[Agent]] = relationship(back_populates="template")
    role: Mapped[Role | None] = relationship(back_populates="behavior_templates")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="offline")
    os_type: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict | None] = mapped_column(JSON, default=None)
    last_seen: Mapped[datetime | None] = mapped_column(TIMESTAMP, default=None)
    last_activity: Mapped[str | None] = mapped_column(String(255), default=None)
    injection_target: Mapped[str | None] = mapped_column(String(200), default=None)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"), default=None)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("behavior_templates.id"), default=None
    )
    version_info: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role | None] = relationship(back_populates="agents")
    template: Mapped[BehaviorTemplate | None] = relationship(back_populates="agents")
    activities: Mapped[list[AgentActivity]] = relationship(back_populates="agent")


class AgentActivity(Base):
    __tablename__ = "agent_activities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), default=None)
    activity_type: Mapped[str | None] = mapped_column(String(50), default=None)
    activity_data: Mapped[dict | None] = mapped_column(JSON, default=None)
    timestamp: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())

    agent: Mapped[Agent | None] = relationship(back_populates="activities")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), index=True, default=None)
    app: Mapped[str] = mapped_column(String(150))
    activity_type: Mapped[str] = mapped_column(String(50))
    role: Mapped[str | None] = mapped_column(String(100), default=None)
    duration_seconds: Mapped[float | None] = mapped_column(default=None)
    context: Mapped[dict | None] = mapped_column(JSON, default=None)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, index=True)

    agent: Mapped[Agent | None] = relationship()
