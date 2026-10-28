"""Reusable deployment targets (the range's hosts), saved once and reused.

Operator-only CRUD. The deploy panel lists these so an operator picks hosts
instead of retyping them each time (#212 follow-up).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Host
from app.schemas import HostCreate, HostResponse

router = APIRouter()


@router.get("/hosts", response_model=list[HostResponse])
def list_hosts(db: Session = Depends(get_db)):
    return db.query(Host).order_by(Host.label).all()


@router.post("/hosts", response_model=HostResponse, status_code=201)
def create_host(payload: HostCreate, db: Session = Depends(get_db)):
    host = Host(
        label=payload.label,
        address=payload.address,
        ssh_user=payload.ssh_user,
        os_type=payload.os_type.value if payload.os_type else None,
    )
    db.add(host)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A host with this address already exists"
        ) from None
    db.refresh(host)
    return host


@router.delete("/hosts/{host_id}", status_code=204)
def delete_host(host_id: int, db: Session = Depends(get_db)):
    host = db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    db.delete(host)
    db.commit()
