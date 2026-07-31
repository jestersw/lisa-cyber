from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.ml_infer import get_inference
from app.models.models import Agent
from app.security import require_agent_token

router = APIRouter()


@router.get("/agents/{agent_id}/next-activity", dependencies=[Depends(require_agent_token)])
def next_activity(
    agent_id: str,
    current: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    state = current or agent.last_activity
    predicted = get_inference().predict(state) if state else None
    if predicted is None:
        return {
            "agent_id": agent_id,
            "current": state,
            "next_activity": get_settings().default_activity,
            "activity_type": "use",
            "source": "fallback",
        }
    return {
        "agent_id": agent_id,
        "current": state,
        "next_activity": predicted,
        "activity_type": "use",
        "source": "model",
    }


@router.get("/ml/status")
def ml_status():
    inference = get_inference()
    inference.ensure_loaded()
    return {
        "model_loaded": inference.loaded,
        "states": inference.state_count,
        "path": str(inference.path),
    }


@router.post("/ml/reload")
def ml_reload():
    inference = get_inference()
    loaded = inference.load()
    return {"reloaded": loaded, "states": inference.state_count}
