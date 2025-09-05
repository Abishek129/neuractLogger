from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from ..store import Store

import sqlite3

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, UniqueConstraint, inspect

# Choose your connection string
DATABASE_URL = "sqlite:///mydatabase.db"  # ✅ SQLite
# DATABASE_URL = "postgresql+psycopg2://user:pass@localhost/mydb"
# DATABASE_URL = "mysql+pymysql://user:pass@localhost/mydb"
# DATABASE_URL = "oracle+cx_oracle://user:pass@host:port/?service_name=..."
# DATABASE_URL = "mssql+pyodbc://user:pass@dsn_name"


router = APIRouter()


@router.get("/schemas")
def list_schemas() -> Dict[str, List[Dict[str, Any]]]:

    result: List[Dict[str, Any]] = []

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)

    tables = inspector.get_table_names()

    for table in tables:
        columns = inspector.get_columns(table)
        column_info = [
            {"name": col['name'], "type": f"{col['type']}"}
            for col in columns
        ]

        result.append({
            "table": table,
            "columns": column_info
        })

    # conn = sqlite3.connect("mydatabase.db")
    # cursor = conn.cursor()

    # result: List[Dict[str, Any]] = []

    # cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    # tables = cursor.fetchall()

    # for table in tables:
    #     table_name = table[0]

    #     if table_name.startswith('sqlite_'):
    #         continue

    #     cursor.execute(f"PRAGMA table_info({table_name});")
    #     columns = cursor.fetchall()

    #     column_info = [
    #         {"name": col[1], "type": col[2]}
    #         for col in columns
    #     ]

    #     result.append({
    #         "table": table_name,
    #         "columns": column_info
    #     })

    # conn.close()
    return {"items": result}
    #return {"items": Store.instance().list_schemas()}


@router.post("/schemas")
def create_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        engine = create_engine(DATABASE_URL)
        metadata = MetaData()

        table_name = list(payload.keys())[0] if payload else "default_table"
    
        users = Table(
            table_name,
            metadata,
        )
        for col in payload[table_name]:
            col_name = col.get("col_name")
            col_type = None
            match col_type:
                case "Integer": col_type = Integer
                case "String": col_type = String
                case _: col_type = String
            if col_name and col_type:
                col = Column(col_name, col_type, primary_key=col.get("primary_key", False), nullable=col.get("nullable", False))
                users.append_column(col)

        metadata.create_all(engine)

        # conn = sqlite3.connect("mydatabase.db")
        # cursor = conn.cursor()

        # table_create_query = f"CREATE TABLE IF NOT EXISTS {table_name} ("
        # for col in payload[table_name]:
        #     col_query = ""
        #     col_name = col.get("col_name")
        #     col_type = col.get("type", "TEXT")
        #     if col_name:
        #         col_query += f"{col_name} {col_type}"
        #     if col.get("primary_key"):
        #         col_query += " PRIMARY KEY"
        #     if col.get("not_null"):
        #         col_query += " NOT NULL"
        #     col_query += ", "
        #     table_create_query += col_query
        # table_create_query = table_create_query.rstrip(", ") + ");"
            
        # print("Executing query:", table_create_query)
        # cursor.execute(table_create_query)

        # conn.commit()
        # conn.close()
        # print("Creating table with payload:", payload)
        return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schemas/export")
def export_schemas() -> Dict[str, Any]:
    return {"schemas": Store.instance().list_schemas()}


@router.post("/schemas/import")
def import_schemas(payload: Dict[str, Any]) -> Dict[str, Any]:
    count = Store.instance().import_schemas(payload.get("schemas") or payload.get("items") or [])
    return {"imported": count}

