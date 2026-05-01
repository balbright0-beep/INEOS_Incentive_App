import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from app.database import get_db
from app.models.program import Program, ProgramRule, ProgramVin, ProgramBulletin
from app.models.budget import Budget, AuditLog
from app.models.transaction import DealTransaction
from app.models.campaign_code import CampaignCodeLayer
from app.schemas.program import ProgramCreate, ProgramUpdate, ProgramResponse
from app.auth.security import get_current_user, require_admin
from app.models.user import User
from app.services.code_matrix import rebuild_matrix
from app.services.vin_list import parse_vin_list

router = APIRouter(prefix="/api/programs", tags=["programs"])


def _enrich_program(db: Session, prog: Program) -> dict:
    """Add computed fields to program response."""
    # VIN list summary for vin_specific programs — count + amount range
    # let the SPA show a one-line summary on the list page without
    # paginating the full VIN dataset.
    vin_summary = None
    if prog.program_type == "vin_specific":
        vin_rows = db.query(ProgramVin.amount).filter(ProgramVin.program_id == prog.id).all()
        amounts = [float(a[0]) for a in vin_rows]
        vin_summary = {
            "count": len(amounts),
            "min_amount": min(amounts) if amounts else 0.0,
            "max_amount": max(amounts) if amounts else 0.0,
            "total_amount": sum(amounts),
        }

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
        "public_facing": bool(getattr(prog, "public_facing", True)),
        "not_stackable_program_ids": list(getattr(prog, "not_stackable_program_ids", None) or []),
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
        "vin_summary": vin_summary,
    }
    return data


@router.get("/public")
def list_public_programs(db: Session = Depends(get_db)):
    """
    Live program summary for the retailer-facing finder. No auth.
    Returns the same fields a retailer needs to understand the offer
    (name, type, dates, per-unit amount, rules, description) and
    deliberately omits internal-only fields like spend-to-date,
    budget caps, and creator id.
    """
    progs = db.query(Program).filter(
        Program.status == "active",
        Program.published == True,  # noqa: E712
    ).order_by(Program.effective_date.desc(), Program.name).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "program_type": p.program_type,
            "effective_date": p.effective_date.isoformat() if p.effective_date else None,
            "expiration_date": p.expiration_date.isoformat() if p.expiration_date else None,
            "description": p.description,
            "stacking_category": p.stacking_category,
            "per_unit_amount": float(p.per_unit_amount or 0),
            "rules": [
                {"rule_type": r.rule_type, "operator": r.operator, "value": r.value}
                for r in p.rules
            ],
        }
        for p in progs
    ]


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
        public_facing=req.public_facing if req.public_facing is not None else True,
        not_stackable_program_ids=req.not_stackable_program_ids or [],
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

    # Two views of the payload:
    #   update_data    — Python types (date objects, Decimals after the
    #                    coerce loop), used for setattr against the
    #                    SQLAlchemy columns.
    #   audit_details  — JSON-mode dump (dates → ISO strings), used as
    #                    the AuditLog.details payload because that
    #                    column is JSON and Python's default encoder
    #                    can't serialize date. Without this the PUT
    #                    blew up with "Object of type date is not JSON
    #                    serializable" → 500 → SPA "Internal Server
    #                    Error" toast.
    update_data = req.model_dump(exclude_unset=True)
    update_data.pop("rules", None)  # rules handled below from req.rules
    audit_details = req.model_dump(exclude_unset=True, mode="json")
    audit_details.pop("rules", None)

    for key, val in update_data.items():
        if key in ("budget_amount", "per_unit_amount") and val is not None:
            val = Decimal(str(val))
        setattr(prog, key, val)

    # Use req.rules (Pydantic objects with attributes) rather than the
    # dict-converted update_data["rules"] — the latter trips on
    # rule.rule_type because dicts don't expose keys as attributes.
    # That AttributeError surfaced as a 500 on every Edit save and was
    # the cause of the persistent "Internal Server Error" toast.
    if "rules" in req.model_fields_set:
        db.query(ProgramRule).filter(ProgramRule.program_id == prog.id).delete()
        for rule in (req.rules or []):
            db.add(ProgramRule(
                program_id=prog.id,
                rule_type=rule.rule_type,
                operator=rule.operator,
                value=rule.value,
            ))

    db.add(AuditLog(
        entity_type="program", entity_id=prog.id,
        action="updated", user_id=user.id, details=audit_details,
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
    # Refresh the matrix on every publish so any matrix-logic change
    # since the last activate (e.g. the loyalty/conquest gate) takes
    # effect at deploy time. Matrix contents don't depend on
    # published, but rebuilding here gives admins a single "click and
    # everything's fresh" action instead of asking them to remember
    # to hit Rebuild on the Code Matrix page.
    matrix = rebuild_matrix(db)
    return {"published": len(promoted), "programs": promoted, "codes_total": len(matrix)}


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
    matrix = rebuild_matrix(db)
    return {"unpublished": len(pulled), "programs": pulled, "codes_total": len(matrix)}


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


# ── VIN-specific program: per-VIN amount list endpoints ──
#
# Used only by program_type='vin_specific'. Replace-all upload
# semantics: each successful POST wipes the program's existing rows
# and writes the new list in a single transaction. That matches how
# admins think about the source spreadsheet ("upload the latest MSRP
# REBATE.xlsx") and avoids a partial-state bug where a botched merge
# leaves stale VINs in the table.

@router.get("/{program_id}/vins")
def list_program_vins(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all VIN+amount rows for a vin_specific program. Sorted
    by VIN for stable display. Returns an empty list (200, not 404)
    when the program is vin_specific but has no rows yet — the SPA
    uses this as the "show empty-state, prompt for upload" signal."""
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    rows = (
        db.query(ProgramVin)
        .filter(ProgramVin.program_id == program_id)
        .order_by(ProgramVin.vin)
        .all()
    )
    return {
        "program_id": program_id,
        "program_type": prog.program_type,
        "count": len(rows),
        "vins": [{"vin": r.vin, "amount": float(r.amount)} for r in rows],
    }


@router.post("/{program_id}/vins/upload")
async def upload_program_vins(
    program_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Replace the program's VIN list from an uploaded Excel workbook.
    Accepts the canonical 2-column shape (VIN, amount) — the parser
    auto-detects which column is which by header keyword, so the source
    spreadsheet doesn't need to be reformatted before upload."""
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    if prog.program_type != "vin_specific":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload VINs to a {prog.program_type} program (vin_specific only).",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        rows, warnings = parse_vin_list(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse workbook: {e}")

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No valid VIN rows found in workbook. " + (
                f"Warnings: {'; '.join(warnings[:5])}" if warnings else ""
            ),
        )

    # Replace-all: drop the old set, write the new one in one tx so a
    # parser failure halfway through the upload can't strand the
    # program with a half-replaced list.
    db.query(ProgramVin).filter(ProgramVin.program_id == program_id).delete()
    for r in rows:
        db.add(ProgramVin(
            program_id=program_id,
            vin=r["vin"],
            amount=Decimal(str(r["amount"])),
        ))
    db.add(AuditLog(
        entity_type="program", entity_id=program_id,
        action="vin_list_uploaded", user_id=user.id,
        details={
            "filename": file.filename,
            "row_count": len(rows),
            "warning_count": len(warnings),
        },
    ))
    db.commit()
    return {
        "program_id": program_id,
        "uploaded": len(rows),
        "warnings": warnings,
        "filename": file.filename,
    }


@router.delete("/{program_id}/vins")
def clear_program_vins(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Remove every VIN row for a vin_specific program. Useful when
    the admin wants a fresh slate before re-uploading."""
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    deleted = db.query(ProgramVin).filter(ProgramVin.program_id == program_id).delete()
    db.add(AuditLog(
        entity_type="program", entity_id=program_id,
        action="vin_list_cleared", user_id=user.id,
        details={"removed": deleted},
    ))
    db.commit()
    return {"program_id": program_id, "removed": deleted}


# ── Supplemental bulletin attachments ──
#
# Distinct from the auto-generated PDF bulletin (services/pdf_generator
# regenerates that one on demand from the program's data). These are
# arbitrary files an admin uploads to ride alongside — Q1 communications,
# OEM updates, signed legal addenda, dealer FAQ, etc. Stored as bytes
# in the row so we don't depend on object storage; PDFs are typically
# small and the dataset is bounded.
#
# Cap individual uploads at 20MB to keep DB rows reasonable. Anything
# bigger likely belongs on a CDN / object store, which we don't have
# wired up yet.
_BULLETIN_MAX_BYTES = 20 * 1024 * 1024
_BULLETIN_ALLOWED_CTYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "image/jpeg",
}


@router.get("/{program_id}/bulletins")
def list_program_bulletins(
    program_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List supplemental bulletins for a program (metadata only — the
    binary payload is fetched separately via GET /bulletins/{id})."""
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    rows = (
        db.query(ProgramBulletin)
        .filter(ProgramBulletin.program_id == program_id)
        .order_by(ProgramBulletin.uploaded_at.desc())
        .all()
    )
    return {
        "program_id": program_id,
        "count": len(rows),
        "bulletins": [
            {
                "id": b.id,
                "filename": b.filename,
                "content_type": b.content_type,
                "size_bytes": b.size_bytes,
                "description": b.description,
                "uploaded_by": b.uploaded_by,
                "uploaded_at": str(b.uploaded_at) if b.uploaded_at else None,
            }
            for b in rows
        ],
    }


@router.post("/{program_id}/bulletins")
async def upload_program_bulletin(
    program_id: str,
    file: UploadFile = File(...),
    description: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Attach a supplemental bulletin to a program. Append-only —
    re-uploading the same filename creates a new row rather than
    replacing, since the new file may be a revision the admin wants
    to keep alongside the previous version. Use DELETE to drop old
    revisions explicitly."""
    prog = db.query(Program).filter(Program.id == program_id).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > _BULLETIN_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(contents):,} bytes). Max is "
                   f"{_BULLETIN_MAX_BYTES // (1024 * 1024)}MB.",
        )

    ctype = (file.content_type or "application/octet-stream").lower()
    if ctype not in _BULLETIN_ALLOWED_CTYPES:
        # Be lenient on the unknown-content-type case — if the
        # filename ends in .pdf assume PDF. Browsers occasionally
        # report octet-stream for files dragged from Finder/Explorer.
        if file.filename and file.filename.lower().endswith(".pdf"):
            ctype = "application/pdf"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ctype}'. Accepted: PDF, "
                       "Word, Excel, PNG, JPEG.",
            )

    bulletin = ProgramBulletin(
        program_id=program_id,
        filename=(file.filename or "bulletin")[:300],
        content_type=ctype,
        size_bytes=len(contents),
        description=(description or "").strip()[:500] or None,
        data=contents,
        uploaded_by=user.id,
    )
    db.add(bulletin)
    db.add(AuditLog(
        entity_type="program", entity_id=program_id,
        action="bulletin_uploaded", user_id=user.id,
        details={"filename": bulletin.filename, "size_bytes": bulletin.size_bytes},
    ))
    db.commit()
    db.refresh(bulletin)
    return {
        "id": bulletin.id,
        "filename": bulletin.filename,
        "content_type": bulletin.content_type,
        "size_bytes": bulletin.size_bytes,
        "description": bulletin.description,
        "uploaded_at": str(bulletin.uploaded_at) if bulletin.uploaded_at else None,
    }


@router.get("/{program_id}/bulletins/{bulletin_id}")
def download_program_bulletin(
    program_id: str,
    bulletin_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream the binary payload back with the original content-type
    + filename so browsers render PDFs inline and force a download
    for everything else."""
    bulletin = (
        db.query(ProgramBulletin)
        .filter(
            ProgramBulletin.id == bulletin_id,
            ProgramBulletin.program_id == program_id,
        )
        .first()
    )
    if not bulletin:
        raise HTTPException(status_code=404, detail="Bulletin not found")
    # PDFs render inline so admins can preview without saving; other
    # types force a download since browsers can't preview them.
    disposition = "inline" if bulletin.content_type == "application/pdf" else "attachment"
    safe_name = bulletin.filename.replace('"', '')
    return Response(
        content=bulletin.data,
        media_type=bulletin.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@router.delete("/{program_id}/bulletins/{bulletin_id}")
def delete_program_bulletin(
    program_id: str,
    bulletin_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Remove a supplemental bulletin. The auto-generated PDF
    bulletin (re-rendered from program data) is unaffected."""
    bulletin = (
        db.query(ProgramBulletin)
        .filter(
            ProgramBulletin.id == bulletin_id,
            ProgramBulletin.program_id == program_id,
        )
        .first()
    )
    if not bulletin:
        raise HTTPException(status_code=404, detail="Bulletin not found")
    filename = bulletin.filename
    db.delete(bulletin)
    db.add(AuditLog(
        entity_type="program", entity_id=program_id,
        action="bulletin_deleted", user_id=user.id,
        details={"bulletin_id": bulletin_id, "filename": filename},
    ))
    db.commit()
    return {"deleted": bulletin_id, "filename": filename}
