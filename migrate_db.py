"""
Add any model columns that are missing from the existing SQLite tables.

db.create_all() only creates missing *tables* -- it never adds columns to a
table that already exists. So when you add a field to a model, an existing
chatti.db keeps the old schema and every query fails with
"no such column: user.<field>".

Run this after changing a model:

    python migrate_db.py
"""

from sqlalchemy import inspect, text

from app import app, db

with app.app_context():
    inspector = inspect(db.engine)
    dialect = db.engine.dialect
    added = 0

    for model in db.Model.__subclasses__():
        table = model.__tablename__

        if table not in inspector.get_table_names():
            # Brand new table -- db.create_all() will handle it below.
            continue

        existing = {c["name"] for c in inspector.get_columns(table)}

        for column in model.__table__.columns:
            if column.name in existing:
                continue

            # SQLite can only ADD COLUMN if it is nullable or has a constant
            # default. Every column we add here is nullable, so this is safe.
            col_type = column.type.compile(dialect=dialect)

            db.session.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {col_type}')
            )
            print(f"  + {table}.{column.name} ({col_type})")
            added += 1

    db.session.commit()

    # Create any tables that did not exist yet.
    db.create_all()

    print(f"Done. {added} column(s) added.")
    for table in inspector.get_table_names():
        cols = ", ".join(c["name"] for c in inspect(db.engine).get_columns(table))
        print(f"  {table}: {cols}")
