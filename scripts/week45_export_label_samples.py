import argparse
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
import asyncpg

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

def main() -> None:
    parser = argparse.ArgumentParser(description="Export random unlabeled suggestions for manual review")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/issues"))
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--repo", default="")
    parser.add_argument("--out", default="reports/week45_label_samples.csv")
    args = parser.parse_args()

    query = """
    SELECT
        ds.id AS suggestion_id,
        ds.repo,
        ds.source_issue_external_id,
        ds.suggested_issue_external_id,
        ds.semantic_score,
        ds.keyword_score,
        ds.structural_score,
        ds.label_score,
        ds.final_score,
        ds.source_signal_strength,
        ds.candidate_signal_strength,
        ds.suggested_at
    FROM duplicate_suggestions ds
    LEFT JOIN suggestion_labels sl ON sl.suggestion_id = ds.id
    WHERE sl.suggestion_id IS NULL
      AND ($1 = '' OR ds.repo = $1)
    ORDER BY RANDOM()
    LIMIT $2
    """

    async def _run() -> None:
        conn = await asyncpg.connect(args.database_url)
        try:
            rows = await conn.fetch(query, args.repo, args.sample_size)
        finally:
            await conn.close()

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "suggestion_id",
                    "repo",
                    "source_issue_external_id",
                    "suggested_issue_external_id",
                    "semantic_score",
                    "keyword_score",
                    "structural_score",
                    "label_score",
                    "final_score",
                    "source_signal_strength",
                    "candidate_signal_strength",
                    "suggested_at",
                    "label",
                    "notes",
                    "labeled_by",
                ],
            )
            writer.writeheader()
            for row in rows:
                record = dict(row)
                record.update({"label": "", "notes": "", "labeled_by": ""})
                writer.writerow(record)

        print(f"exported_samples={len(rows)} out={args.out}")

    import asyncio

    asyncio.run(_run())


if __name__ == "__main__":
    main()
