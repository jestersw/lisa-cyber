import random

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.models import Agent
from app.models_store import get_store, restrict_model
from app.security import require_agent, require_operator

router = APIRouter()


def _agent_applications(agent: Agent) -> list[str]:
    apps = (agent.config or {}).get("applications", [])
    return [app for app in apps if isinstance(app, str)]


def _agent_role(agent: Agent) -> str | None:
    if agent.role:
        return agent.role.name
    return (agent.config or {}).get("agent_info", {}).get("role")


def _sample(counts: dict[str, int], rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    apps = list(counts)
    return rng.choices(apps, weights=[counts[app] for app in apps], k=1)[0]


def _global_counts(model: dict) -> dict[str, int]:
    """Aggregate a model's per-state next-app counts into one global marginal.
    Used for back-off (#51): for a state unseen in training we predict from the
    overall next-app distribution instead of a constant fallback. Derived from
    the same `counts` artifact, so no retraining or artifact change."""
    agg: dict[str, int] = {}
    for bucket in model.get("counts", {}).values():
        for app, n in bucket.items():
            agg[app] = agg.get(app, 0) + n
    return agg


@router.get("/agents/{agent_id}/next-activity")
def next_activity(
    current: str | None = Query(default=None),
    sample: bool = Query(default=False),
    agent: Agent = Depends(require_agent),
    db: Session = Depends(get_db),
):
    agent_id = agent.agent_id
    applications = _agent_applications(agent)
    state = current or agent.last_activity
    model = get_store().for_role(_agent_role(agent))
    trimmed = restrict_model(model, applications) if model and applications else None

    counts = (trimmed or {}).get("counts", {}).get(state) if state else None
    source = "model"
    if not counts and trimmed:
        # State unseen in training: back off to the model's global marginal (a
        # data-driven guess) rather than a constant. Same artifact, strictly
        # better than the old fixed fallback (#51).
        global_counts = _global_counts(trimmed)
        if global_counts:
            counts = global_counts
            source = "backoff"

    if not counts:
        fallback = applications[0] if applications else get_settings().default_activity
        return {
            "agent_id": agent_id,
            "current": state,
            "next_activity": fallback,
            "activity_type": "use",
            "source": "fallback",
            "trained_on": None,
        }

    predicted = _sample(counts) if sample else max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    total = sum(counts.values())
    return {
        "agent_id": agent_id,
        "current": state,
        "next_activity": predicted,
        "activity_type": "use",
        "source": source,
        "trained_on": trimmed.get("trained_on") if trimmed else None,
        "distribution": {app: round(n / total, 3) for app, n in counts.items()},
    }


@router.get("/ml/status", dependencies=[Depends(require_operator)])
def ml_status():
    store = get_store()
    shared = store.get("_shared")
    return {
        "models_dir": str(store.directory),
        "shared_loaded": shared is not None,
        "shared_states": len(shared.get("counts", {})) if shared else 0,
    }


@router.post("/ml/reload", dependencies=[Depends(require_operator)])
def ml_reload():
    store = get_store()
    store.clear()
    shared = store.get("_shared")
    return {
        "reloaded": shared is not None,
        "shared_states": len(shared.get("counts", {})) if shared else 0,
    }
