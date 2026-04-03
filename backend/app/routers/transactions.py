from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.transaction import DealTransaction
from app.schemas.transaction import TransactionResponse, TransactionUpdate, ImportResult
from app.auth.security import get_current_user, require_admin
from app.models.user import User
from app.services.import_service import import_daily_report
from app.config import settings

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("/import", response_model=ImportResult)
async def import_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx)")
    content = await file.read()
    if len(content) > settings.UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    result = import_daily_report(db, content, file.filename)
    return ImportResult(**result)


@router.get("")
def list_transactions(
    payment_status: str = Query(None),
    dealer_ship_to: str = Query(None),
    campaign_code: str = Query(None),
    anomalies_only: bool = Query(False),
    skip: int = Query(0),
    limit: int = Query(100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(DealTransaction)

    # Retailers only see their own dealer's transactions
    if user.role == "retailer" and user.dealer_id:
        from app.models.dealer import Dealer
        dealer = db.query(Dealer).filter(Dealer.id == user.dealer_id).first()
        if dealer:
            q = q.filter(DealTransaction.dealer_ship_to == dealer.ship_to_code)

    if payment_status:
        q = q.filter(DealTransaction.payment_status == payment_status)
    if dealer_ship_to:
        q = q.filter(DealTransaction.dealer_ship_to == dealer_ship_to)
    if campaign_code:
        q = q.filter(DealTransaction.campaign_code == campaign_code)
    if anomalies_only:
        q = q.filter(DealTransaction.anomaly_flag != None, DealTransaction.anomaly_resolved == "N")

    total = q.count()
    txns = q.order_by(DealTransaction.import_date.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [TransactionResponse.model_validate(t).model_dump() for t in txns],
    }


@router.get("/anomalies")
def list_anomalies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    txns = db.query(DealTransaction).filter(
        DealTransaction.anomaly_flag != None,
        DealTransaction.anomaly_resolved == "N",
    ).order_by(DealTransaction.import_date.desc()).all()
    return [TransactionResponse.model_validate(t).model_dump() for t in txns]


@router.put("/{txn_id}")
def update_transaction(
    txn_id: str, req: TransactionUpdate,
    db: Session = Depends(get_db), user: User = Depends(require_admin),
):
    txn = db.query(DealTransaction).filter(DealTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for key, val in req.model_dump(exclude_unset=True).items():
        setattr(txn, key, val)
    db.commit()
    return TransactionResponse.model_validate(txn)
