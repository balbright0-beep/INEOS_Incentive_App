import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.pay_file import PayFile
from app.models.transaction import DealTransaction
from app.schemas.payfile import PayFileResponse, PayFileGenerate, PayFileAdjustment
from app.schemas.transaction import TransactionResponse
from app.auth.security import require_admin
from app.models.user import User
from app.services.pay_file_service import generate_pay_file

router = APIRouter(prefix="/api/payfiles", tags=["payfiles"])


@router.post("/generate")
def generate(
    req: PayFileGenerate,
    adjustments: list[PayFileAdjustment] = [],
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    adj_dicts = [a.model_dump() for a in adjustments] if adjustments else None
    pf = generate_pay_file(db, req.period, adj_dicts)
    return {
        "id": pf.id,
        "period": pf.period,
        "total_amount": float(pf.total_amount),
        "total_units": int(pf.total_units),
        "status": pf.status,
        "file_path": pf.file_path,
    }


@router.get("")
def list_payfiles(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    pfs = db.query(PayFile).order_by(PayFile.generated_date.desc()).all()
    return [
        {
            "id": pf.id,
            "period": pf.period,
            "generated_date": str(pf.generated_date) if pf.generated_date else None,
            "total_amount": float(pf.total_amount or 0),
            "total_units": int(pf.total_units or 0),
            "status": pf.status,
            "file_path": pf.file_path,
        }
        for pf in pfs
    ]


@router.get("/{payfile_id}")
def get_payfile(payfile_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    pf = db.query(PayFile).filter(PayFile.id == payfile_id).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Pay file not found")
    txns = db.query(DealTransaction).filter(DealTransaction.pay_file_id == pf.id).all()
    return {
        "id": pf.id,
        "period": pf.period,
        "generated_date": str(pf.generated_date) if pf.generated_date else None,
        "total_amount": float(pf.total_amount or 0),
        "total_units": int(pf.total_units or 0),
        "status": pf.status,
        "file_path": pf.file_path,
        "transactions": [TransactionResponse.model_validate(t).model_dump() for t in txns],
    }


@router.get("/{payfile_id}/download")
def download_payfile(payfile_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    pf = db.query(PayFile).filter(PayFile.id == payfile_id).first()
    if not pf or not pf.file_path or not os.path.exists(pf.file_path):
        raise HTTPException(status_code=404, detail="Pay file not found or file missing")
    return FileResponse(
        pf.file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(pf.file_path),
    )


@router.post("/{payfile_id}/submit")
def submit_payfile(payfile_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    pf = db.query(PayFile).filter(PayFile.id == payfile_id).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Pay file not found")
    pf.status = "submitted"
    db.query(DealTransaction).filter(DealTransaction.pay_file_id == pf.id).update(
        {"payment_status": "submitted"}
    )
    db.commit()
    return {"message": "Pay file submitted"}


@router.post("/{payfile_id}/confirm")
def confirm_payfile(payfile_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    pf = db.query(PayFile).filter(PayFile.id == payfile_id).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Pay file not found")
    pf.status = "confirmed"
    db.query(DealTransaction).filter(DealTransaction.pay_file_id == pf.id).update(
        {"payment_status": "paid"}
    )
    db.commit()
    return {"message": "Pay file confirmed, transactions marked as paid"}
