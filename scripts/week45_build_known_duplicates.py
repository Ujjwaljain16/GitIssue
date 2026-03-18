import argparse
import asyncio
import os
import re
from pathlib import Path

from dotenv import load_dotenv
import asyncpg
import httpx

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PATTERNS = [
    re.compile(r"duplicate\s+of\s+#(\d+)", re.IGNORECASE),
    re.compile(r"dupe\s+of\s+#(\d+)", re.IGNORECASE),
    re.compile(r"duplicates?\s+#(\d+)", re.IGNORECASE),
]


def _extract_duplicate_refs(text: str) -> set[int]:
    refs: set[int] = set()
    if not text:
        return refs
    for pattern in PATTERNS:
        refs.update(int(m.group(1)) for m in pattern.finditer(text))
    return refs


async def _upsert_known_duplicate(conn, repo: str, source_no: int, target_no: int, evidence: str) -> None:
    source = f"github:{repo}#{source_no}"
    target = f"github:{repo}#{target_no}"
    await conn.execute(
        """
        INSERT INTO known_duplicates (repo, source_external_id, target_external_id, evidence)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (repo, source_external_id, target_external_id) DO NOTHING
        """,
        repo,
        source,
        target,
        evidence,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build known duplicate baseline from real GitHub issue/comment text")
    parser.add_argument("--repos", required=True, help="Comma-separated owner/repo list")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/issues"))
    parser.add_argument("--max-issues", type=int, default=300)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("GITHUB_TOKEN is required")

    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    headers = {
        "Authorization": f"Bearer {args.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "git-issue-tracker-week45",
    }

    conn = await asyncpg.connect(args.database_url)
    total_edges = 0

    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            for repo in repos:
                page = 1
                seen_issues = 0
                repo_edges = 0

                while seen_issues < args.max_issues:
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo}/issues",
                        params={"state": "all", "per_page": 100, "page": page, "sort": "updated", "direction": "desc"},
                    )
                    resp.raise_for_status()
                    issues = resp.json()
                    if not issues:
                        break

                    for issue in issues:
                        if "pull_request" in issue:
                            continue

                        source_no = int(issue["number"])
                        seen_issues += 1

                        for target_no in _extract_duplicate_refs(issue.get("body") or ""):
                            await _upsert_known_duplicate(conn, repo, source_no, target_no, "issue_body")
                            repo_edges += 1

                        comments_resp = await client.get(issue["comments_url"], params={"per_page": 50})
                        comments_resp.raise_for_status()
                        for comment in comments_resp.json():
                            for target_no in _extract_duplicate_refs(comment.get("body") or ""):
                                await _upsert_known_duplicate(conn, repo, source_no, target_no, "issue_comment")
                                repo_edges += 1

                        if seen_issues >= args.max_issues:
                            break

                    page += 1

                total_edges += repo_edges
                print(f"repo={repo} scanned_issues={seen_issues} extracted_edges={repo_edges}")
    finally:
        await conn.close()

    print(f"done repos={len(repos)} total_known_duplicate_edges={total_edges}")


if __name__ == "__main__":
    asyncio.run(main())
