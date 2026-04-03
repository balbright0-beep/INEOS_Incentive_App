from datetime import date, datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.transaction import DealTransaction
from app.models.program import Program
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.models.dealer import Dealer
from app.models.budget import Budget
from app.auth.security import get_current_user, require_admin_or_rbm
from app.models.user import User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/spend-summary")
def spend_summary(
    period: str = Query(None, description="Period like 2026-04"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not period:
        today = date.today()
        period = today.strftime("%Y-%m")

    q = db.query(
        func.coalesce(func.sum(DealTransaction.support_amount), 0).label("total_spend"),
        func.count(DealTransaction.id).label("total_units"),
    ).filter(
        func.strftime("%Y-%m", DealTransaction.retail_date) == period
    )

    if user.role == "rbm" and user.region:
        q = q.join(Dealer, DealTransaction.dealer_ship_to == Dealer.ship_to_code).filter(
            Dealer.region == user.region
        )

    result = q.first()
    total_spend = float(result.total_spend) if result else 0
    total_units = result.total_units if result else 0

    # Total budget for the period
    total_budget = float(db.query(func.coalesce(func.sum(Budget.allocated_amount), 0)).filter(
        Budget.period == period
    ).scalar() or 0)

    utilization = (total_spend / total_budget * 100) if total_budget > 0 else 0
    avg_per_unit = (total_spend / total_units) if total_units > 0 else 0

    # Project month-end based on daily run rate
    today = date.today()
    days_elapsed = today.day
    days_in_month = 30
    daily_rate = total_spend / days_elapsed if days_elapsed > 0 else 0
    projected = daily_rate * days_in_month

    return {
        "total_spend_mtd": total_spend,
        "total_budget": total_budget,
        "utilization_pct": round(utilization, 1),
        "total_units_mtd": total_units,
        "avg_incentive_per_unit": round(avg_per_unit, 2),
        "projected_month_end": round(projected, 2),
        "period": period,
    }


@router.get("/spend-by-program")
def spend_by_program(
    period: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_rbm),
):
    if not period:
        period = date.today().strftime("%Y-%m")

    programs = db.query(Program).filter(Program.status.in_(["active", "expired"])).all()
    result = []
    for prog in programs:
        code_ids = [l.campaign_code_id for l in
                    db.query(CampaignCodeLayer.campaign_code_id).filter(
                        CampaignCodeLayer.program_id == prog.id).all()]
        if not code_ids:
            continue
        codes = [c.code for c in db.query(CampaignCode.code).filter(CampaignCode.id.in_(code_ids)).all()]
        if not codes:
            continue
        q = db.query(
            func.coalesce(func.sum(DealTransaction.support_amount), 0),
            func.count(DealTransaction.id),
        ).filter(
            DealTransaction.campaign_code.in_(codes),
            func.strftime("%Y-%m", DealTransaction.retail_date) == period,
        )
        row = q.first()
        budget = db.query(func.coalesce(func.sum(Budget.allocated_amount), 0)).filter(
            Budget.program_id == prog.id, Budget.period == period
        ).scalar() or 0
        result.append({
            "program_name": prog.name,
            "program_type": prog.program_type,
            "spend": float(row[0]) if row else 0,
            "units": row[1] if row else 0,
            "budget": float(budget),
        })
    return result


@router.get("/spend-by-region")
def spend_by_region(
    period: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_rbm),
):
    if not period:
        period = date.today().strftime("%Y-%m")

    results = (
        db.query(
            Dealer.region,
            func.coalesce(func.sum(DealTransaction.support_amount), 0),
            func.count(DealTransaction.id),
        )
        .join(Dealer, DealTransaction.dealer_ship_to == Dealer.ship_to_code)
        .filter(func.strftime("%Y-%m", DealTransaction.retail_date) == period)
        .group_by(Dealer.region)
        .all()
    )
    return [
        {"region": r[0] or "Unknown", "spend": float(r[1]), "units": r[2]}
        for r in results
    ]


@router.get("/spend-by-dealer")
def spend_by_dealer(
    period: str = Query(None),
    region: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_rbm),
):
    if not period:
        period = date.today().strftime("%Y-%m")

    q = (
        db.query(
            DealTransaction.dealer_ship_to,
            DealTransaction.dealer_name,
            func.coalesce(func.sum(DealTransaction.support_amount), 0),
            func.count(DealTransaction.id),
        )
        .filter(func.strftime("%Y-%m", DealTransaction.retail_date) == period)
        .group_by(DealTransaction.dealer_ship_to, DealTransaction.dealer_name)
    )

    if region:
        q = q.join(Dealer, DealTransaction.dealer_ship_to == Dealer.ship_to_code).filter(
            Dealer.region == region
        )
    elif user.role == "rbm" and user.region:
        q = q.join(Dealer, DealTransaction.dealer_ship_to == Dealer.ship_to_code).filter(
            Dealer.region == user.region
        )

    results = q.all()
    return [
        {
            "ship_to_code": r[0] or "",
            "dealer_name": r[1] or "",
            "region": "",
            "spend": float(r[2]),
            "units": r[3],
            "avg_per_unit": round(float(r[2]) / r[3], 2) if r[3] > 0 else 0,
        }
        for r in results
    ]


@router.get("/pacing")
def pacing(
    period: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_rbm),
):
    if not period:
        period = date.today().strftime("%Y-%m")

    # Daily spend for pacing chart
    daily = (
        db.query(
            func.strftime("%Y-%m-%d", DealTransaction.retail_date).label("day"),
            func.sum(DealTransaction.support_amount).label("spend"),
            func.count(DealTransaction.id).label("units"),
        )
        .filter(func.strftime("%Y-%m", DealTransaction.retail_date) == period)
        .group_by(func.strftime("%Y-%m-%d", DealTransaction.retail_date))
        .order_by("day")
        .all()
    )

    total_budget = float(db.query(func.coalesce(func.sum(Budget.allocated_amount), 0)).filter(
        Budget.period == period
    ).scalar() or 0)

    return {
        "period": period,
        "total_budget": total_budget,
        "daily": [
            {"date": d[0], "spend": float(d[1] or 0), "units": d[2]}
            for d in daily
        ],
    }
