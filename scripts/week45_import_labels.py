import argparse
import asyncio
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
import asyncpg

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

VALID_LABELS = {"true_positive", "false_positive", "related_not_duplicate", "cant_tell"}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import reviewer labels into suggestion_labels")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/issues"))
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()

    conn = await asyncpg.connect(args.database_url)
    imported = 0

    try:
        with open(args.csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                label = (row.get("label") or "").strip()
                if not label:
                    continue
                if label not in VALID_LABELS:
                    raise ValueError(f"Invalid label '{label}' for suggestion_id={row.get('suggestion_id')}")

                suggestion_id = int(row["suggestion_id"])
                notes = (row.get("notes") or "").strip() or None
                labeled_by = (row.get("labeled_by") or "").strip() or None

                await conn.execute(
                    """
                    INSERT INTO suggestion_labels (suggestion_id, label, notes, labeled_by)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (suggestion_id) DO UPDATE
                    SET label = EXCLUDED.label,
                        notes = EXCLUDED.notes,
                        labeled_by = EXCLUDED.labeled_by,
                        labeled_at = NOW()
                    """,
                    suggestion_id,
                    label,
                    notes,
                    labeled_by,
                )
                imported += 1
    finally:
        await conn.close()

    print(f"labels_imported={imported}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
