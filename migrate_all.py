# migrate_all.py
# One-shot, idempotent runner for the ENTIRE schema.
#
# Ensures every table and column the app expects exists, by:
#   1. running db.create_all()  -> creates any missing tables
#   2. running every migrate_*.py in this folder (each is written to be
#      idempotent: ADD COLUMN IF NOT EXISTS, DO-block guarded constraints,
#      and column-existence checks for the rename/backfill migrations)
#
# Safe to run as many times as you like. Run it after every deploy, or once
# to catch up a database that missed individual migrations:
#
#     python migrate_all.py
#
# Exits non-zero if any migration fails, and prints a summary so you can see
# exactly which step had a problem.

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.basename(__file__)

# Performance indexes reference columns that other migrations add, so run that
# one LAST. Everything else is independent and order-insensitive.
RUN_LAST = {"migrate_performance_indexes.py"}


def discover():
    files = sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(HERE, "migrate_*.py"))
    )
    files = [f for f in files if f != SELF]
    ordered = [f for f in files if f not in RUN_LAST]
    ordered += [f for f in files if f in RUN_LAST]
    return ordered


def create_all():
    print("== db.create_all() (ensure tables) ==")
    from app import app
    from extensions import db
    with app.app_context():
        db.create_all()
    print("  ok\n")


def run_one(fname):
    print(f"== {fname} ==")
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, fname)],
        capture_output=True, text=True,
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if out:
        print("  " + out.replace("\n", "\n  "))
    ok = result.returncode == 0
    if not ok:
        # Show stderr only on failure, so success stays quiet.
        if err:
            print("  " + err.replace("\n", "\n  "))
        print(f"  ✗ FAILED (exit {result.returncode})")
    else:
        print("  ✓ ok")
    print()
    return ok


def main():
    try:
        create_all()
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ create_all() failed: {exc}\n")
        return 1

    migrations = discover()
    print(f"Running {len(migrations)} migrations...\n")

    failed = []
    for fname in migrations:
        if not run_one(fname):
            failed.append(fname)

    print("=" * 48)
    if failed:
        print(f"DONE with {len(failed)} failure(s):")
        for f in failed:
            print(f"  - {f}")
        return 1
    print(f"DONE — all {len(migrations)} migrations succeeded. Schema is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
