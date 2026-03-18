import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import asyncpg

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _pct(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 2)


def _f1(precision: float, recall: float) -> float:
    p = precision / 100.0
    r = recall / 100.0
    if p + r == 0:
        return 0.0
    return round((2 * p * r / (p + r)) * 100.0, 2)


def _classify_failure(row: asyncpg.Record) -> str:
    structural = float(row.get("structural_score") or 0.0)
    keyword = float(row.get("keyword_score") or 0.0)
    source_strength = float(row.get("source_signal_strength") or 0.0)
    candidate_strength = float(row.get("candidate_signal_strength") or 0.0)
    repo = (row.get("repo") or "").lower()

    if structural < 0.15 and keyword > 0.5:
        return "template_similarity"
    if source_strength < 0.3 and candidate_strength < 0.3:
        return "generic_symptom"
    if source_strength < 0.3 or candidate_strength < 0.3:
        return "shared_dependency"
    if "/" in repo and any(k in repo for k in ["awesome", "public-apis"]):
        return "cross_repo_noise"
    return "version_confusion"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compute Week 4.5 live validation metrics and report")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/issues"))
    parser.add_argument("--repo", default="")
    parser.add_argument("--out", default="reports/week45_report.json")
    args = parser.parse_args()

    conn = await asyncpg.connect(args.database_url)
    try:
        where_repo = "AND ($1 = '' OR ds.repo = $1)"

        labeled = await conn.fetch(
            f"""
            SELECT ds.*, sl.label
            FROM duplicate_suggestions ds
            JOIN suggestion_labels sl ON sl.suggestion_id = ds.id
            WHERE 1=1 {where_repo}
            """,
            args.repo,
        )

        tp = sum(1 for r in labeled if r["label"] == "true_positive")
        fp = sum(1 for r in labeled if r["label"] == "false_positive")
        related = sum(1 for r in labeled if r["label"] == "related_not_duplicate")
        cant_tell = sum(1 for r in labeled if r["label"] == "cant_tell")

        precision = _pct(tp, tp + fp)

        known_total = await conn.fetchval(
            "SELECT COUNT(*) FROM known_duplicates WHERE ($1 = '' OR repo = $1)",
            args.repo,
        )
        known_detected = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM known_duplicates kd
            WHERE ($1 = '' OR kd.repo = $1)
              AND EXISTS (
                SELECT 1
                FROM duplicate_suggestions ds
                                WHERE (
                                        ds.source_issue_external_id = kd.source_external_id
                                        AND ds.suggested_issue_external_id = kd.target_external_id
                                )
                                OR (
                                        ds.source_issue_external_id = kd.target_external_id
                                        AND ds.suggested_issue_external_id = kd.source_external_id
                                )
              )
            """,
            args.repo,
        )
        recall = _pct(float(known_detected), float(known_total or 0))

        thresholds = [round(x / 100.0, 2) for x in range(50, 100, 5)]
        pr_curve = []
        for threshold in thresholds:
            subset = [r for r in labeled if float(r["final_score"] or 0.0) >= threshold]
            tp_t = sum(1 for r in subset if r["label"] == "true_positive")
            fp_t = sum(1 for r in subset if r["label"] == "false_positive")
            precision_t = _pct(tp_t, tp_t + fp_t)

            known_detected_t = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM known_duplicates kd
                WHERE ($1 = '' OR kd.repo = $1)
                  AND EXISTS (
                    SELECT 1
                    FROM duplicate_suggestions ds
                    WHERE (
                        (
                            ds.source_issue_external_id = kd.source_external_id
                            AND ds.suggested_issue_external_id = kd.target_external_id
                        )
                        OR (
                            ds.source_issue_external_id = kd.target_external_id
                            AND ds.suggested_issue_external_id = kd.source_external_id
                        )
                    )
                    AND ds.final_score >= $2
                  )
                """,
                args.repo,
                threshold,
            )
            recall_t = _pct(float(known_detected_t), float(known_total or 0))
            pr_curve.append(
                {
                    "threshold": threshold,
                    "precision": precision_t,
                    "recall": recall_t,
                    "f1": _f1(precision_t, recall_t),
                }
            )

        best_f1_row = max(pr_curve, key=lambda r: r["f1"]) if pr_curve else {"threshold": 0.85, "f1": 0.0}

        taxonomy_counter = Counter()
        for row in labeled:
            if row["label"] == "false_positive":
                taxonomy_counter[_classify_failure(row)] += 1

        total_comments = await conn.fetchval(
            "SELECT COUNT(*) FROM bot_comments bc JOIN issues i ON i.external_id = bc.issue_external_id WHERE ($1 = '' OR i.repo = $1)",
            args.repo,
        )
        positive_engagement = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM duplicate_suggestions ds
            WHERE ($1 = '' OR ds.repo = $1)
              AND ds.user_feedback IN ('correct', 'helpful', 'accepted')
            """,
            args.repo,
        )
        negative_engagement = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM duplicate_suggestions ds
            WHERE ($1 = '' OR ds.repo = $1)
              AND ds.user_feedback IN ('incorrect', 'not_helpful', 'rejected')
            """,
            args.repo,
        )

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_filter": args.repo or "all",
            "labels": {
                "total": len(labeled),
                "true_positive": tp,
                "false_positive": fp,
                "related_not_duplicate": related,
                "cant_tell": cant_tell,
            },
            "metrics": {
                "precision_percent": precision,
                "recall_percent": recall,
                "engagement_rate_percent": _pct(float(positive_engagement), float(total_comments or 0)),
                "negative_rate_percent": _pct(float(negative_engagement), float(total_comments or 0)),
            },
            "known_duplicates": {
                "total": int(known_total or 0),
                "detected": int(known_detected or 0),
            },
            "threshold_recommendation": {
                "strategy": "max_f1",
                "recommended_threshold": best_f1_row["threshold"],
                "f1_percent": best_f1_row["f1"],
            },
            "pr_curve": pr_curve,
            "error_taxonomy_false_positive": dict(taxonomy_counter),
            "go_no_go": {
                "precision_pass": precision >= 70.0,
                "recall_pass": recall >= 30.0,
                "engagement_pass": (total_comments == 0) or (_pct(float(positive_engagement), float(total_comments or 0)) >= 15.0),
                "negative_pass": (total_comments == 0) or (_pct(float(negative_engagement), float(total_comments or 0)) <= 5.0),
            },
        }

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(json.dumps(report["metrics"], indent=2))
        print(f"recommended_threshold={report['threshold_recommendation']['recommended_threshold']}")
        print(f"report={args.out}")
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
