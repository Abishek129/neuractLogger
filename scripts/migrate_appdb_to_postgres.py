import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.plc_agent.api import appdb


TABLE_SPECS: Dict[str, List[str]] = {
    "app_meta": ["key"],
    "app_schemas": ["id"],
    "app_schema_fields": ["schema_id", "key"],
    "app_db_targets": ["id"],
    "app_device_tables": ["id"],
    "app_gateways": ["id"],
    "app_devices": ["id"],
    "app_jobs": ["id"],
    "app_job_runs": ["id"],
    "app_metrics_jobs_minute": ["job_id", "minute_utc"],
    "app_metrics_system_minute": ["minute_utc"],
    "app_job_errors_minute": ["job_id", "code", "minute_utc"],
}

COLUMN_MAPPINGS: Dict[str, Dict[str, str]] = {
    "app_schema_fields": {"desc": "desc_text"},
}


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _pg_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=:t AND table_schema=current_schema()"
        ),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _upsert_sql(table: str, cols: List[str], conflict_cols: List[str]) -> str:
    insert_cols = ", ".join(cols)
    placeholders = ", ".join([f":{c}" for c in cols])
    if conflict_cols:
        update_cols = [c for c in cols if c not in conflict_cols]
        if update_cols:
            updates = ", ".join([f"{c}=excluded.{c}" for c in update_cols])
            return (
                f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
                f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {updates}"
            )
        return (
            f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        )
    return f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate app.db (SQLite) metadata to Postgres APP_DB_URL.")
    parser.add_argument("--sqlite-path", help="Path to source app.db (defaults to legacy location).")
    parser.add_argument("--pg-url", help="Postgres connection string (defaults to APP_DB_URL).")
    args = parser.parse_args()

    pg_url = args.pg_url or os.environ.get("APP_DB_URL")
    if not pg_url:
        print("APP_DB_URL is required for Postgres metadata.")
        return 2

    os.environ["APP_DB_URL"] = pg_url

    sqlite_path = Path(args.sqlite_path) if args.sqlite_path else appdb.app_db_path()
    if not sqlite_path.exists():
        print(f"SQLite source not found: {sqlite_path}")
        return 3

    appdb.init()

    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    try:
        src_tables = _sqlite_tables(src)
        engine = create_engine(pg_url, pool_pre_ping=True)
        with engine.begin() as pg_conn:
            for table, conflict_cols in TABLE_SPECS.items():
                if table not in src_tables:
                    continue
                src_cols = _sqlite_columns(src, table)
                dst_cols = _pg_columns(pg_conn, table)
                col_map = COLUMN_MAPPINGS.get(table, {})
                pairs = []
                for src_col in src_cols:
                    dst_col = col_map.get(src_col, src_col)
                    if dst_col in dst_cols:
                        pairs.append((src_col, dst_col))
                if not pairs:
                    continue
                select_cols = [p[0] for p in pairs]
                dest_cols = [p[1] for p in pairs]
                rows = src.execute(f"SELECT {', '.join(select_cols)} FROM {table}").fetchall()
                if not rows:
                    continue
                sql = _upsert_sql(table, dest_cols, conflict_cols)
                for row in rows:
                    payload = {dst: row[src] for src, dst in pairs}
                    pg_conn.execute(text(sql), payload)
                print(f"{table}: {len(rows)} row(s)")
    finally:
        src.close()

    print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
