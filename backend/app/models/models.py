from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Boolean,
    ForeignKey,
    String,
    Text,
    false,
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
    binary_url: Mapped[str | None] = mapped_column(String(500), default=None)
    # Real per-agent token, hashed, set when the agent enrolls (#201). Null
    # before enrollment.
    agent_token: Mapped[str | None] = mapped_column(String(200), default=None)
    # One-time enrollment token (hashed), baked into the built binary; the agent
    # exchanges it for its real token at install time, then it is cleared (#201
    # part B). Null for dev agents that were never built.
    enrollment_token_hash: Mapped[str | None] = mapped_column(String(200), default=None)
    # True once the agent has exchanged its enrollment token for a real one.
    enrolled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    installer_url: Mapped[str | None] = mapped_column(String(500), default=None)
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


class Deployment(Base):
    """One attempt to push/update an agent onto a set of target hosts via an
    orchestration backend (Ansible today, #212). The operator triggers it from
    the panel; the runner updates status + output as the playbook runs."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # The agent being deployed (its string USR id, matching the API path and
    # the builds endpoint). Not a hard FK so a deployment record survives even
    # if the agent row is later removed.
    agent_id: Mapped[str] = mapped_column(String(50), index=True)
    backend: Mapped[str] = mapped_column(String(20), default="ansible")
    # pending -> running -> succeeded | failed | unavailable
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # The request payload (targets + options), kept for audit / re-run.
    targets: Mapped[dict | None] = mapped_column(JSON, default=None)
    returncode: Mapped[int | None] = mapped_column(default=None)
    output: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, default=None)


class Host(Base):
    """A reusable deployment target in the range, saved by the operator so hosts
    don't have to be retyped on every deploy."""

    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(253), unique=True)
    ssh_user: Mapped[str | None] = mapped_column(String(64), default=None)
    os_type: Mapped[str | None] = mapped_column(String(20), default=None)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=func.now())


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
