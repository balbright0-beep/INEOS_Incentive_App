"""Seed data loader for initial setup."""

from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.dealer import Dealer, Product
from app.models.program import Program, ProgramRule
from app.models.budget import Budget
from app.auth.security import hash_password
from app.services.stacking import seed_default_stacking


DEALERS = [
    # Northeast - Darren McNeill
    ("1004001", "FELDMAN INEOS GRENADIER", "northeast", "Darren McNeill", "MI"),
    ("1004002", "HERON INEOS GRENADIER", "northeast", "Darren McNeill", "NY"),
    ("1004003", "GRENADIER OF GREENWICH", "northeast", "Darren McNeill", "CT"),
    ("1004004", "INEOS GRENADIER BOSTON", "northeast", "Darren McNeill", "MA"),
    ("1004005", "GRENADIER OF LONG ISLAND", "northeast", "Darren McNeill", "NY"),
    ("1004006", "INEOS GRENADIER PHILADELPHIA", "northeast", "Darren McNeill", "PA"),
    ("1004007", "GRENADIER OF NEW JERSEY", "northeast", "Darren McNeill", "NJ"),
    ("1004008", "INEOS GRENADIER PITTSBURGH", "northeast", "Darren McNeill", "PA"),
    ("1004009", "GRENADIER OF DETROIT", "northeast", "Darren McNeill", "MI"),
    ("1004010", "INEOS GRENADIER MINNEAPOLIS", "northeast", "Darren McNeill", "MN"),
    # Southeast - Frederick Valdez
    ("1004101", "GRENADIER OF TAMPA", "southeast", "Frederick Valdez", "FL"),
    ("1004102", "GRENADIER OF MIAMI", "southeast", "Frederick Valdez", "FL"),
    ("1004103", "INEOS GRENADIER ATLANTA", "southeast", "Frederick Valdez", "GA"),
    ("1004104", "GRENADIER OF CHARLOTTE", "southeast", "Frederick Valdez", "NC"),
    ("1004105", "INEOS GRENADIER NASHVILLE", "southeast", "Frederick Valdez", "TN"),
    ("1004106", "GRENADIER OF RALEIGH", "southeast", "Frederick Valdez", "NC"),
    ("1004107", "INEOS GRENADIER CHARLESTON", "southeast", "Frederick Valdez", "SC"),
    ("1004108", "GRENADIER OF JACKSONVILLE", "southeast", "Frederick Valdez", "FL"),
    ("1004109", "INEOS GRENADIER RICHMOND", "southeast", "Frederick Valdez", "VA"),
    ("1004110", "GRENADIER OF ORLANDO", "southeast", "Frederick Valdez", "FL"),
    # Central - Brant Scott
    ("1004201", "INEOS GRENADIER DALLAS", "central", "Brant Scott", "TX"),
    ("1004202", "GRENADIER OF HOUSTON", "central", "Brant Scott", "TX"),
    ("1004203", "INEOS GRENADIER AUSTIN", "central", "Brant Scott", "TX"),
    ("1004204", "GRENADIER OF DENVER", "central", "Brant Scott", "CO"),
    ("1004205", "INEOS GRENADIER CHICAGO", "central", "Brant Scott", "IL"),
    ("1004206", "GRENADIER OF KANSAS CITY", "central", "Brant Scott", "MO"),
    ("1004207", "INEOS GRENADIER ST LOUIS", "central", "Brant Scott", "MO"),
    ("1004208", "GRENADIER OF SAN ANTONIO", "central", "Brant Scott", "TX"),
    ("1004209", "INEOS GRENADIER OKLAHOMA CITY", "central", "Brant Scott", "OK"),
    # Western - Matt Messerly
    ("1004383", "MOSSY INEOS GRENADIER SAN DIEGO", "western", "Matt Messerly", "CA"),
    ("1004301", "GRENADIER OF MARIN", "western", "Matt Messerly", "CA"),
    ("1004302", "INEOS GRENADIER LOS ANGELES", "western", "Matt Messerly", "CA"),
    ("1004303", "GRENADIER OF SCOTTSDALE", "western", "Matt Messerly", "AZ"),
    ("1004304", "INEOS GRENADIER SEATTLE", "western", "Matt Messerly", "WA"),
    ("1004305", "GRENADIER OF PORTLAND", "western", "Matt Messerly", "OR"),
    ("1004306", "INEOS GRENADIER SALT LAKE CITY", "western", "Matt Messerly", "UT"),
    ("1004307", "GRENADIER OF HAWAII", "western", "Matt Messerly", "HI"),
    ("1004308", "INEOS GRENADIER LAS VEGAS", "western", "Matt Messerly", "NV"),
]

PRODUCTS = [
    # MY25
    ("MY25", "station_wagon", "Base", None, 71500),
    ("MY25", "station_wagon", "Fieldmaster", None, 73500),
    ("MY25", "station_wagon", "Belstaff", None, 76000),
    ("MY25", "station_wagon", "Trialmaster", None, 79500),
    ("MY25", "quartermaster", "Base", None, 73500),
    ("MY25", "quartermaster", "Fieldmaster", None, 75500),
    ("MY25", "quartermaster", "Belstaff", None, 78000),
    ("MY25", "quartermaster", "Trialmaster", None, 81500),
    # MY26
    ("MY26", "station_wagon", "Base", None, 73000),
    ("MY26", "station_wagon", "Fieldmaster", None, 75000),
    ("MY26", "station_wagon", "Belstaff", None, 77500),
    ("MY26", "station_wagon", "Trialmaster", None, 81000),
    ("MY26", "station_wagon", "Highlands", None, 83000),
    ("MY26", "quartermaster", "Base", None, 75000),
    ("MY26", "quartermaster", "Fieldmaster", None, 77000),
    ("MY26", "quartermaster", "Belstaff", None, 79500),
    ("MY26", "quartermaster", "Trialmaster", None, 83000),
    ("MY26", "quartermaster", "Highlands", None, 85000),
    # Special Editions
    ("MY25", "station_wagon", "Arcane Works Detour", "arcane_works_detour", 105000),
    ("MY27", "station_wagon", "Iceland Tactical", "iceland_tactical", None),
]


def seed_database(db: Session):
    """Seed the database with initial data."""
    # Check if already seeded
    if db.query(User).count() > 0:
        return

    # Users
    admin = User(
        username="admin",
        password_hash=hash_password("admin123"),
        role="admin",
        name="Sales Planning Admin",
    )
    db.add(admin)

    rbms = [
        ("darren", "Darren McNeill", "northeast"),
        ("frederick", "Frederick Valdez", "southeast"),
        ("brant", "Brant Scott", "central"),
        ("matt", "Matt Messerly", "western"),
    ]
    for uname, name, region in rbms:
        db.add(User(
            username=uname, password_hash=hash_password("rbm123"),
            role="rbm", name=name, region=region,
        ))

    # Dealers
    dealer_map = {}
    for ship_to, name, region, rbm, state in DEALERS:
        d = Dealer(ship_to_code=ship_to, name=name, region=region, rbm=rbm, state=state)
        db.add(d)
        db.flush()
        dealer_map[ship_to] = d

    # Create a retailer user for the first dealer of each region
    for ship_to in ["1004001", "1004101", "1004201", "1004383"]:
        d = dealer_map.get(ship_to)
        if d:
            db.add(User(
                username=f"dealer_{ship_to}",
                password_hash=hash_password("dealer123"),
                role="retailer",
                name=f"{d.name} User",
                dealer_id=d.id,
            ))

    # Products
    for my, body, trim, special, msrp in PRODUCTS:
        db.add(Product(
            model_year=my, body_style=body, trim=trim,
            special_edition=special,
            msrp=Decimal(str(msrp)) if msrp else None,
        ))

    db.flush()

    # Stacking rules
    seed_default_stacking(db)

    # Sample Programs (draft)
    p1 = Program(
        name="April 2026 Customer Cash",
        program_type="customer_cash",
        status="draft",
        effective_date=date(2026, 4, 1),
        expiration_date=date(2026, 4, 30),
        budget_amount=Decimal("500000"),
        per_unit_amount=Decimal("5000"),
        description="Customer cash incentive for April 2026 across all body styles.",
        created_by=admin.id,
    )
    db.add(p1)
    db.flush()
    db.add(ProgramRule(program_id=p1.id, rule_type="body_style", operator="in", value=["station_wagon", "quartermaster"]))
    db.add(ProgramRule(program_id=p1.id, rule_type="model_year", operator="in", value=["MY25", "MY26"]))
    db.add(Budget(program_id=p1.id, period="2026-04", allocated_amount=Decimal("500000")))

    p2 = Program(
        name="April 2026 Loyalty Rebate",
        program_type="loyalty",
        status="draft",
        effective_date=date(2026, 4, 1),
        expiration_date=date(2026, 4, 30),
        budget_amount=Decimal("150000"),
        per_unit_amount=Decimal("1500"),
        description="Loyalty rebate for existing INEOS households.",
        created_by=admin.id,
    )
    db.add(p2)
    db.flush()
    db.add(ProgramRule(program_id=p2.id, rule_type="body_style", operator="in", value=["station_wagon", "quartermaster"]))
    db.add(Budget(program_id=p2.id, period="2026-04", allocated_amount=Decimal("150000")))

    p3 = Program(
        name="April 2026 Conquest Rebate",
        program_type="conquest",
        status="draft",
        effective_date=date(2026, 4, 1),
        expiration_date=date(2026, 4, 30),
        budget_amount=Decimal("200000"),
        per_unit_amount=Decimal("2500"),
        description="Conquest rebate for competitive trade-ins.",
        created_by=admin.id,
    )
    db.add(p3)
    db.flush()
    db.add(ProgramRule(program_id=p3.id, rule_type="body_style", operator="in", value=["station_wagon", "quartermaster"]))
    db.add(Budget(program_id=p3.id, period="2026-04", allocated_amount=Decimal("200000")))

    p4 = Program(
        name="April 2026 APR Cash",
        program_type="apr_cash",
        status="draft",
        effective_date=date(2026, 4, 1),
        expiration_date=date(2026, 4, 30),
        budget_amount=Decimal("100000"),
        per_unit_amount=Decimal("0"),
        description="APR subvention support through Santander.",
        created_by=admin.id,
    )
    db.add(p4)
    db.flush()
    db.add(ProgramRule(program_id=p4.id, rule_type="body_style", operator="in", value=["station_wagon", "quartermaster"]))
    db.add(ProgramRule(program_id=p4.id, rule_type="model_year", operator="in", value=["MY26"]))
    db.add(Budget(program_id=p4.id, period="2026-04", allocated_amount=Decimal("100000")))

    p5 = Program(
        name="April 2026 CVP",
        program_type="cvp",
        status="draft",
        effective_date=date(2026, 4, 1),
        expiration_date=date(2026, 4, 30),
        budget_amount=Decimal("75000"),
        per_unit_amount=Decimal("3000"),
        description="Courtesy Vehicle Program with 30-day in-service minimum and 6,000-mile cap.",
        created_by=admin.id,
    )
    db.add(p5)
    db.flush()
    db.add(ProgramRule(program_id=p5.id, rule_type="body_style", operator="in", value=["station_wagon", "quartermaster"]))
    db.add(Budget(program_id=p5.id, period="2026-04", allocated_amount=Decimal("75000")))

    db.commit()
