"""AI assistant for agent behaviour debugging (#211).

Collects the signals we already store for one agent (status, heartbeats,
activity events, last build error) and runs them through the existing LLM
provider to produce a grounded diagnosis + suggested config fixes.

Best-effort by design: when the LLM is unavailable or returns junk, the endpoint
still returns 200 with the deterministic observations as findings (source
"unavailable"), so the operator always gets something actionable. Operator-only
(wired in main.py).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import generate_diagnosis
from app.models.models import Agent
from app.schemas import DiagnoseResponse, DiagnosisFinding
from app.services.diagnose import collect_signals

log = logging.getLogger("lisa.diagnose")

router = APIRouter()


@router.post("/agents/{agent_id}/diagnose", response_model=DiagnoseResponse)
def diagnose_agent(agent_id: str, db: Session = Depends(get_db)) -> DiagnoseResponse:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    signals, observations = collect_signals(db, agent)

    diagnosis = generate_diagnosis(signals, observations)
    if diagnosis is not None:
        return DiagnoseResponse(
            agent_id=agent_id,
            source="model",
            summary=diagnosis["summary"],
            findings=diagnosis["findings"],
            suggested_changes=diagnosis["suggested_changes"],
            signals=signals,
        )

    # LLM down or invalid output: fall back to the deterministic observations.
    log.info("diagnose %s: LLM unavailable, returning observations only", agent_id)
    findings = [DiagnosisFinding(issue=o, severity="warning") for o in observations]
    summary = (
        "LLM analysis is unavailable; showing automatic observations from the agent's signals."
        if observations
        else "LLM analysis is unavailable, and no problems were detected in the collected signals."
    )
    return DiagnoseResponse(
        agent_id=agent_id,
        source="unavailable",
        summary=summary,
        findings=findings,
        suggested_changes=[],
        signals=signals,
    )
