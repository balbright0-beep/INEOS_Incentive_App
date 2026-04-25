import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from app.database import get_db
from app.models.program import Program, ProgramRule
from app.models.budget import Budget, AuditLog
from app.models.transaction import DealTransaction
from app.models.campaign_code import CampaignCodeLayer
from app.schemas.program import ProgramCreate, ProgramUpdate, ProgramResponse
from app.auth.security import get_current_user, require_admin
from app.models.user import User
from app.services.code_matrix import rebuild_matrix

router = APIRouter(prefix="/api/programs", tags=["programs"])


def _enrich_program(db: Session, prog: Program) -> dict:
    """Add computed fields to program response."""
    # Calculate spend and units
    code_ids = [l.campaign_code_id for l in db.query(CampaignCodeLayer.campaign_code_id).filter(
        CampaignCodeLayer.program_id == prog.id
    ).all()]

    spend = 0.0
    units = 0
    if code_ids:
        result = db.query(
            func.coalesce(func.sum(DealTransaction.support_amount), 0),
            func.count(DealTransaction.id),
        ).filter(DealTransaction.campaign_code.in_(
            [c.code for c in db.query(
                __import__('app.models.campaign_code', fromlist=['CampaignCode']).CampaignCode
            ).filter(
                __import__('app.models.campaign_code', fromlist=['CampaignCode']).CampaignCode.id.in_(code_ids)
            ).all()]
        )).first()
        if result:
            spend = float(result[0])
            units = result[1]

    # Phase derives from status + published. The frontend uses this
    # to render the right badge (Draft / Staged / Live / Expired) and
    # the right action button (Activate vs Publish vs Unpublish).
    if prog.status == "active":
        phase = "live" if getattr(prog, "published", False) else "staged"
    else:
        phase = prog.status  # draft / expired / cancelled
    data = {
        "id": prog.id,
        "name": prog.name,
        "program_type": prog.program_type,
        "status": prog.status,
        "published": bool(getattr(prog, "published", False)),
        "phase": phase,
        "effective_date": prog.effective_date,
        "expiration_date": prog.expiration_date,
        "budget_amount": float(prog.budget_amount) if prog.budget_amount else None,
        "budget_units": int(prog.budget_units) if prog.budget_units else None,
        "description": prog.description,
        "stacking_category": prog.stacking_category,
        "per_unit_amount": float(prog.per_unit_amount) if prog.per_unit_amount else 0,
        "created_by": prog.created_by,
        "created_at": str(prog.created_at) if prog.created_at else None,
        "updated_at": str(prog.updated_at) if prog.updated_at else None,
        "rules": [{"id": r.id, "rule_type": r.rule_type, "operator": r.operator, "value": r.value}
                  for r in prog.rules],
        "budgets": [{"id": b.id, "period": b.period,
                     "allocated_amount": float(b.allocated_amount),
                     "allocated_units": int(b.allocated_units) if b.allocated_units else None}
                    for b in prog.budgets],
        "spend_to_date": spend,
        "units_to_date": units,
    }
    return data


@router.get("")
def list_programs(
    status: str = Query(None),
    program_type: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Program)
    if status:
        q = q.filter(Program.status == status)
    if program_type:
        q = q.filter(Program.program_type == program_type)
    programs = q.order_by(Program.created_at.desc()).all()
    return [_enrich_program(db, p) for p in programs]


@router.post("")
def create_program(
    req: ProgramCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    prog = Program(
        name=req.name,
        program_type=req.program_type,
        status="draft",
        effective_date=req.effective_date,
        expiration_date=req.expiration_date,
        description=req.description,
        budget_amount=Decimal(str(req.budget_amount)) if req.budget_amount else None,
        budget_units=req.budget_units,
        per_unit_amount=Decimal(str(req.per_unit_amount)) if req.per_unit_amount else Decimal("0"),
        stacking_category=req.stacking_category or req.program_type,
        created_by=user.id,
    )
    db.add(prog)
    db.flush()

    for rule in req.rules:
        db.add(ProgramRule(
            program_id=prog.id,
            rule_type=rule.rule_type,
            operator=rule.operator,
            value=rule.value,
        ))

    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="created", user_id=user.id,
    ))
    db.commit()
    return _enrich_program(db, prog)


@router.get("/{program_id}")
def get_program(program_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    return _enrich_program(db, prog)


@router.put("/{program_id}")
def update_program(
    program_id: str,
    req: ProgramUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")

    update_data = req.model_dump(exclude_unset=True)
    rules_data = update_data.pop("rules", None)

    for key, val in update_data.items():
        if key in ("budget_amount", "per_unit_amount") and val is not None:
            val = Decimal(str(val))
        setattr(prog, key, val)

    if rules_data is not None:
        db.query(ProgramRule).filter(ProgramRule.program_id == prog.id).delete()
        for rule in rules_data:
            db.add(ProgramRule(
                program_id=prog.id,
                rule_type=rule.rule_type,
                operator=rule.operator,
                value=rule.value,
            ))

    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="updated", user_id=user.id, details=update_data,
    ))
    db.commit()
    return _enrich_program(db, prog)


@router.post("/{program_id}/activate")
def activate_program(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Promote a draft to STAGED. The program enters the active code matrix
    and is visible to authenticated admins / RBMs / retailers via the
    internal lookup, but is gated off the public /lookup/ page until an
    admin explicitly calls /publish.
    """
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    prog.status = "active"
    # Activation never auto-publishes — the whole point of the gate is
    # that an admin gets a sanity-check window. Setting published=False
    # explicitly here also handles re-activating a previously-cancelled
    # program: it goes back to staged, not straight to production.
    prog.published = False
    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="activated", user_id=user.id,
        details={"phase": "staged"},
    ))
    db.commit()

    # Rebuild code matrix
    matrix = rebuild_matrix(db)
    return {"message": "Program staged", "phase": "staged", "codes_generated": len(matrix)}


@router.post("/publish-all")
def publish_all_staged(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Bulk-publish every staged program in one click \u2014 the master
    "deploy this build" action. Atomic: either every staged program
    flips to published=True or none do (single transaction). Programs
    that are already live aren't touched. Drafts can't be published
    by this endpoint (they have to be staged first), which prevents
    a stray draft from sneaking onto the public page.
    """
    staged = db.query(Program).filter(
        Program.status == "active",
        Program.published == False,  # noqa: E712 — SQL boolean compare
    ).all()
    if not staged:
        return {"published": 0, "programs": []}
    promoted = []
    for prog in staged:
        prog.published = True
        promoted.append({"id": prog.id, "name": prog.name})
        db.add(AuditLog(
            entity_type="program", entity_id=prog.id,
            action="published", user_id=user.id,
            details={"phase": "live", "via": "publish-all"},
        ))
    db.commit()
    return {"published": len(promoted), "programs": promoted}


@router.post("/unpublish-all")
def unpublish_all_live(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Pull every live program back to staged in one shot. Escape hatch
    for "we just published something wrong, take it down" — the
    matrix and authenticated lookup are unaffected, only the public
    /lookup/ page goes dark.
    """
    live = db.query(Program).filter(
        Program.status == "active",
        Program.published == True,  # noqa: E712
    ).all()
    if not live:
        return {"unpublished": 0, "programs": []}
    pulled = []
    for prog in live:
        prog.published = False
        pulled.append({"id": prog.id, "name": prog.name})
        db.add(AuditLog(
            entity_type="program", entity_id=prog.id,
            action="unpublished", user_id=user.id,
            details={"phase": "staged", "via": "unpublish-all"},
        ))
    db.commit()
    return {"unpublished": len(pulled), "programs": pulled}


@router.post("/{program_id}/publish")
def publish_program(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Promote a STAGED program to LIVE — it now shows on the public
    /lookup/ page. Refuses to publish a draft (must stage first) so
    the staging window can't be skipped accidentally.
    """
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    if prog.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish a {prog.status} program. Activate it to staging first.",
        )
    if prog.published:
        return {"message": "Program already live", "phase": "live"}
    prog.published = True
    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="published", user_id=user.id,
        details={"phase": "live"},
    ))
    db.commit()
    return {"message": "Program published", "phase": "live"}


@router.post("/{program_id}/unpublish")
def unpublish_program(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Pull a LIVE program back to STAGED — useful if a number was wrong
    and we need to remove it from the public page while we fix it.
    Doesn't delete or deactivate; the matrix and authenticated lookup
    still show it.
    """
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    if not prog.published:
        return {"message": "Program already staged", "phase": "staged"}
    prog.published = False
    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="unpublished", user_id=user.id,
        details={"phase": "staged"},
    ))
    db.commit()
    return {"message": "Program pulled back to staging", "phase": "staged"}


@router.post("/{program_id}/clone")
def clone_program(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")

    new_prog = Program(
        name=f"{prog.name} (Copy)",
        program_type=prog.program_type,
        status="draft",
        effective_date=prog.effective_date,
        expiration_date=prog.expiration_date,
        description=prog.description,
        budget_amount=prog.budget_amount,
        budget_units=prog.budget_units,
        per_unit_amount=prog.per_unit_amount,
        stacking_category=prog.stacking_category,
        created_by=user.id,
    )
    db.add(new_prog)
    db.flush()

    for rule in prog.rules:
        db.add(ProgramRule(
            program_id=new_prog.id,
            rule_type=rule.rule_type,
            operator=rule.operator,
            value=rule.value,
        ))

    db.commit()
    return _enrich_program(db, new_prog)


@router.delete("/{program_id}")
def delete_program(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    if prog.status == "active":
        raise HTTPException(status_code=400, detail="Cannot delete an active program. Cancel it first.")
    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="deleted", user_id=user.id,
    ))
    db.delete(prog)
    db.commit()
    return {"message": "Program deleted"}
