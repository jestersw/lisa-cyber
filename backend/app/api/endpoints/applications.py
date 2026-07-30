from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import ApplicationTemplate
from app.schemas import (
    ApplicationTemplateCreate,
    ApplicationTemplateResponse,
    ApplicationTemplateUpdate,
)

router = APIRouter()


@router.post("/application-templates", response_model=ApplicationTemplateResponse)
def create_application_template(t: ApplicationTemplateCreate, db: Session = Depends(get_db)):
    if (
        db.query(ApplicationTemplate)
        .filter(ApplicationTemplate.name == t.name, ApplicationTemplate.is_active.is_(True))
        .first()
    ):
        raise HTTPException(status_code=400, detail=f"Template '{t.name}' already exists")
    db_t = ApplicationTemplate(
        name=t.name,
        display_name=t.display_name,
        category=t.category,
        description=t.description,
        version=t.version,
        author=t.author,
        template_config=t.template_config,
        os_type=t.os_type.value,
    )
    db.add(db_t)
    db.commit()
    db.refresh(db_t)
    return db_t


@router.get("/application-templates", response_model=list[ApplicationTemplateResponse])
def list_application_templates(
    category: str | None = None,
    os_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(ApplicationTemplate).filter(ApplicationTemplate.is_active.is_(True))
    if category:
        query = query.filter(ApplicationTemplate.category == category)
    if os_type:
        query = query.filter(ApplicationTemplate.os_type == os_type)
    return query.offset(skip).limit(limit).all()


@router.get("/application-templates/{template_id}", response_model=ApplicationTemplateResponse)
def get_application_template(template_id: int, db: Session = Depends(get_db)):
    t = (
        db.query(ApplicationTemplate)
        .filter(ApplicationTemplate.id == template_id, ApplicationTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


@router.put("/application-templates/{template_id}", response_model=ApplicationTemplateResponse)
def update_application_template(
    template_id: int, upd: ApplicationTemplateUpdate, db: Session = Depends(get_db)
):
    t = (
        db.query(ApplicationTemplate)
        .filter(ApplicationTemplate.id == template_id, ApplicationTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    data = upd.model_dump(exclude_unset=True)
    if "os_type" in data and data["os_type"] is not None:
        data["os_type"] = data["os_type"].value
    for field, value in data.items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/application-templates/{template_id}")
def delete_application_template(template_id: int, db: Session = Depends(get_db)):
    t = (
        db.query(ApplicationTemplate)
        .filter(ApplicationTemplate.id == template_id, ApplicationTemplate.is_active.is_(True))
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    t.is_active = False
    db.commit()
    return {"message": f"Template '{t.name}' deleted"}
