"""Create the database tables (and any missing columns).

    python init_db.py

Safe to run repeatedly. `app.py` already does this on import, so this is only
a convenience for setting up a database ahead of time.
"""

from app import app, db, ensure_schema

with app.app_context():
    added = ensure_schema()

    for column in added:
        print(f"  + {column}")

    print(f"Database ready. {len(added)} column(s) added.")
    for table in db.metadata.tables:
        print(f"  {table}")
