from __future__ import annotations

import argparse
from pathlib import Path

from portfolio_mvp.db import get_supabase
from portfolio_mvp.parsers.hsbc_cn_pdf import parse_hsbc_cn_pdf
from portfolio_mvp.repository import complete_import, create_import_record, file_sha256, import_normalized_rows, log_import_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Import HSBC China PDF statement.")
    parser.add_argument("pdf_path", type=Path)
    args = parser.parse_args()

    client = get_supabase(use_service_role=True)
    import_id = create_import_record(
        client,
        source="hsbc_china",
        source_type="pdf",
        file_name=args.pdf_path.name,
        file_hash=file_sha256(args.pdf_path),
    )
    rows = parse_hsbc_cn_pdf(args.pdf_path)
    if not rows:
        log_import_error(
            client,
            import_id,
            None,
            {"file": str(args.pdf_path)},
            "No recognizable HSBC China rows found. Add a脱敏样例 PDF to improve parser rules.",
        )
        complete_import(client, import_id, 0, "needs_review", "No recognizable rows found.")
        print("No recognizable rows found. Import marked as needs_review.")
        return
    imported = import_normalized_rows(client, rows, import_id)
    complete_import(client, import_id, imported, "completed")
    print(f"Imported {imported} rows from {args.pdf_path}")


if __name__ == "__main__":
    main()

