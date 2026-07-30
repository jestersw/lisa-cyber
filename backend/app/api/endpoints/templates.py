from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import BehaviorTemplate, Role
from app.schemas import (
    BehaviorTemplateCreate,
    BehaviorTemplateResponse,
    BehaviorTemplateUpdate,
)

router = APIRouter()


@router.post("/behavior-templates", response_model=BehaviorTemplateResponse)
def create_behavior_template(t: BehaviorTemplateCreate, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == t.role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {t.role_id} not found; create it first")
    if (
        db.query(BehaviorTemplate)
        .filter(BehaviorTemplate.name == t.name, BehaviorTemplate.is_active.is_(True))
        .first()
    ):
        raise HTTPException(status_code=400, detail=f"Template '{t.name}' already exists")
    db_t = BehaviorTemplate(
        name=t.name,
        description=t.description,
        role_id=t.role_id,
        template_data=t.template_data,
        os_type=t.os_type.value,
        version=t.version,
    )
    db.add(db_t)
    db.commit()
    db.refresh(db_t)
    return db_t


@router.get("/behavior-templates", response_model=list[BehaviorTemplateResponse])
def list_behavior_templates(
    role_id: int | None = None,
    os_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(BehaviorTemplate).filter(BehaviorTemplate.is_active.is_(True))
    if role_id:
        query = query.filter(BehaviorTemplate.role_id == role_id)
    if os_type:
        query = query.filter(BehaviorTemplate.os_type == os_type)
    return query.offset(skip).limit(limit).all()


@router.get("/behavior-templates/{template_id}", response_model=BehaviorTemplateResponse)
def get_behavior_template(template_id: int, db: Session = Depends(get_db)):
    t = (
        db.query(BehaviorTemplate)
        .filter(BehaviorTemplate.id == template_id, BehaviorTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


@router.put("/behavior-templates/{template_id}", response_model=BehaviorTemplateResponse)
def update_behavior_template(
    template_id: int, upd: BehaviorTemplateUpdate, db: Session = Depends(get_db)
):
    t = (
        db.query(BehaviorTemplate)
        .filter(BehaviorTemplate.id == template_id, BehaviorTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if upd.role_id and upd.role_id != t.role_id:
        if not db.query(Role).filter(Role.id == upd.role_id, Role.is_active.is_(True)).first():
            raise HTTPException(status_code=404, detail=f"Role {upd.role_id} not found")
    data = upd.model_dump(exclude_unset=True)
    if "os_type" in data and data["os_type"] is not None:
        data["os_type"] = data["os_type"].value
    for field, value in data.items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/behavior-templates/{template_id}")
def delete_behavior_template(template_id: int, db: Session = Depends(get_db)):
    t = (
        db.query(BehaviorTemplate)
        .filter(BehaviorTemplate.id == template_id, BehaviorTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    t.is_active = False
    db.commit()
    return {"message": f"Template '{t.name}' deleted"}
