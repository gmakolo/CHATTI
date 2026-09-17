"""Add any model columns that are missing from the existing SQLite tables.

db.create_all() only creates missing *tables* -- it never adds columns to a
table that already exists. So when you add a field to a model, an existing
chatti.db keeps the old schema and every query fails with
"no such column: user.<field>".

`app.py` now runs the same migration on import, so this script is only needed
if you want to see what it did:

    python migrate_db.py
"""

from sqlalchemy import inspect

from app import app, db, ensure_schema

with app.app_context():
    added = ensure_schema()

    for column in added:
        print(f"  + {column}")

    print(f"Done. {len(added)} column(s) added.")

    inspector = inspect(db.engine)
    for table in inspector.get_table_names():
        cols = ", ".join(c["name"] for c in inspector.get_columns(table))
        print(f"  {table}: {cols}")
