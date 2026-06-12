"""Staff management API — CRUD for store employees."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.core.response import api_response
from app.database import get_db
from app.models.models import Staff, User

router = APIRouter(prefix="/api/staff", tags=["staff"])


@router.get("")
def list_staff(
    store_id: int = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    """List staff, optionally filtered by store and status."""
    q = db.query(Staff)
    if store_id:
        q = q.filter(Staff.store_id == store_id)
    if status:
        q = q.filter(Staff.status == status)
    rows = q.order_by(Staff.store_id, Staff.name).all()
    return api_response(data=[{
        "id": r.id, "store_id": r.store_id, "name": r.name,
        "phone": r.phone, "role": r.role, "email": r.email,
        "id_number": r.id_number, "hire_date": str(r.hire_date) if r.hire_date else None,
        "status": r.status, "salary": r.salary, "notes": r.notes,
        "created_at": str(r.created_at),
    } for r in rows])


@router.post("")
def create_staff(
    body: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Add a new staff member."""
    staff = Staff(
        store_id=body.get("store_id", 0),
        name=body["name"],
        phone=body.get("phone", ""),
        role=body.get("role", "staff"),
        email=body.get("email", ""),
        id_number=body.get("id_number", ""),
        hire_date=body.get("hire_date"),
        salary=body.get("salary", 0),
        notes=body.get("notes", ""),
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return api_response(data={"id": staff.id, "name": staff.name}, message="员工已添加")


@router.put("/{staff_id}")
def update_staff(
    staff_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Update staff info."""
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        return api_response(code=-1, message="员工不存在")
    for field in ["name", "phone", "role", "email", "id_number",
                   "hire_date", "status", "salary", "notes", "store_id"]:
        if field in body:
            setattr(staff, field, body[field])
    db.commit()
    return api_response(data={"id": staff.id, "name": staff.name}, message="员工信息已更新")


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Remove a staff member."""
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        return api_response(code=-1, message="员工不存在")
    db.delete(staff)
    db.commit()
    return api_response(message="员工已删除")
