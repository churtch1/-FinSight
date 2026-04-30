from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from portfolio_mvp.repositories.common import json_safe

if TYPE_CHECKING:
    from supabase import Client


def create_import_record(
    client: "Client",
    source: str,
    source_type: str,
    file_name: str | None = None,
    file_hash: str | None = None,
    parser_name: str | None = None,
    parser_version: str | None = None,
) -> str:
    payload = {
        "source": source,
        "source_type": source_type,
        "file_name": file_name,
        "file_hash": file_hash,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "status": "started",
    }
    data = client.table("statement_imports").upsert(payload, on_conflict="source,file_hash").execute().data
    if data:
        return data[0]["id"]
    rows = (
        client.table("statement_imports")
        .select("id")
        .eq("source", source)
        .eq("file_hash", file_hash)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["id"]


def complete_import(
    client: "Client",
    import_id: str,
    rows_imported: int,
    status: str = "completed",
    error_summary: str | None = None,
) -> None:
    client.table("statement_imports").update(
        {
            "status": status,
            "rows_imported": rows_imported,
            "error_summary": error_summary,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", import_id).execute()


def log_import_error(
    client: "Client",
    import_id: str,
    row_number: int | None,
    raw_payload: dict[str, Any] | None,
    message: str,
    severity: str = "error",
) -> None:
    client.table("import_errors").insert(
        {
            "statement_import_id": import_id,
            "row_number": row_number,
            "raw_payload": json_safe(raw_payload or {}),
            "error_message": message,
            "severity": severity,
        }
    ).execute()

