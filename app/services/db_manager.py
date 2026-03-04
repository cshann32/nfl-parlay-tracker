"""
DB Manager — gives the app full unrestricted control over PostgreSQL.
Execute raw SQL, inspect schema, manage tables, run arbitrary DDL/DML.
"""
import logging
from typing import Any
from sqlalchemy import text, inspect
from app.extensions import db
from app.exceptions import DatabaseException

logger = logging.getLogger("nfl.db")


def execute_sql(sql: str, params: dict | None = None) -> list[dict]:
    """Execute raw SQL and return results as list of dicts."""
    logger.info("Executing raw SQL", extra={"sql": sql[:200], "params": params})
    try:
        result = db.session.execute(text(sql), params or {})
        db.session.commit()
        if result.returns_rows:
            rows = result.fetchall()
            keys = result.keys()
            return [dict(zip(keys, row)) for row in rows]
        return []
    except Exception as exc:
        db.session.rollback()
        logger.error("Raw SQL failed", extra={"sql": sql[:200], "error": str(exc)}, exc_info=True)
        raise DatabaseException(f"SQL execution failed: {exc}", detail={"sql": sql[:200]}) from exc


def get_table_names() -> list[str]:
    """List all table names in the database."""
    inspector = inspect(db.engine)
    return inspector.get_table_names()


def get_table_columns(table_name: str) -> list[dict]:
    """Return column definitions for a table."""
    inspector = inspect(db.engine)
    return inspector.get_columns(table_name)


def get_table_row_count(table_name: str) -> int:
    """Return row count for a table."""
    try:
        result = db.session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return result.scalar() or 0
    except Exception as exc:
        logger.warning("Could not count rows", extra={"table": table_name, "error": str(exc)})
        return -1


def get_db_stats() -> dict:
    """Return stats for all tables: name, row count, column count."""
    tables = get_table_names()
    stats = []
    for table in sorted(tables):
        try:
            cols = get_table_columns(table)
            rows = get_table_row_count(table)
            stats.append({"table": table, "rows": rows, "columns": len(cols)})
        except Exception as exc:
            stats.append({"table": table, "rows": -1, "columns": -1, "error": str(exc)})
    return {"tables": stats, "total_tables": len(tables)}


def add_column(table_name: str, column_name: str, column_type: str) -> None:
    """Add a column to an existing table (DDL)."""
    sql = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{column_name}" {column_type}'
    logger.warning("Adding column", extra={"table": table_name, "column": column_name, "type": column_type})
    execute_sql(sql)


def drop_column(table_name: str, column_name: str) -> None:
    """Drop a column from a table (DDL)."""
    sql = f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "{column_name}"'
    logger.warning("Dropping column", extra={"table": table_name, "column": column_name})
    execute_sql(sql)


def truncate_table(table_name: str) -> None:
    """Truncate a table (removes all rows, keeps structure)."""
    sql = f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE'
    logger.warning("Truncating table", extra={"table": table_name})
    execute_sql(sql)


def upsert(table_name: str, data: dict, conflict_column: str) -> None:
    """
    Generic upsert: INSERT ... ON CONFLICT (conflict_column) DO UPDATE.
    Use for bulk sync operations when ORM overhead is too slow.
    """
    if not data:
        return
    cols = list(data.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(f'"{c}"' for c in cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != conflict_column)
    sql = (
        f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT ("{conflict_column}") DO UPDATE SET {updates}'
    )
    execute_sql(sql, data)
