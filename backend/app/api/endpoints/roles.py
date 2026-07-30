from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Agent, Role
from app.schemas import RoleCreate, RoleResponse, RoleUpdate

router = APIRouter()


@router.post("/roles", response_model=RoleResponse)
def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    if db.query(Role).filter(Role.name == role.name, Role.is_active.is_(True)).first():
        raise HTTPException(status_code=400, detail=f"Role '{role.name}' already exists")
    db_role = Role(name=role.name, description=role.description, category=role.category)
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    category: str | None = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    query = db.query(Role).filter(Role.is_active.is_(True))
    if category:
        query = query.filter(Role.category == category)
    return query.offset(skip).limit(limit).all()


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.put("/roles/{role_id}", response_model=RoleResponse)
def update_role(role_id: int, upd: RoleUpdate, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if upd.name and upd.name != role.name:
        clash = (
            db.query(Role)
            .filter(Role.name == upd.name, Role.is_active.is_(True), Role.id != role_id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="Role name already exists")
    for field, value in upd.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    active = (
        db.query(Agent)
        .filter(Agent.role_id == role_id, Agent.status.in_(["online", "active"]))
        .count()
    )
    if active:
        raise HTTPException(
            status_code=400, detail=f"Cannot delete role: {active} active agents use it"
        )
    role.is_active = False
    db.commit()
    return {"message": f"Role '{role.name}' deleted"}
