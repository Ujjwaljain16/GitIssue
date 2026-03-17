"""GitHub comment bot with idempotency tracking."""

import logging
from typing import Optional

from app.db import get_db_pool

logger = logging.getLogger(__name__)


async def setup_bot_comments_table() -> None:
    """Create bot_comments tracking table (idempotent)."""
    pool = get_db_pool()
    
    query = """
    CREATE TABLE IF NOT EXISTS bot_comments (
        id SERIAL PRIMARY KEY,
        issue_external_id TEXT UNIQUE NOT NULL,
        comment_github_id BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """
    
    async with pool.acquire() as conn:
        await conn.execute(query)


async def has_comment(issue_external_id: str) -> bool:
    """Check if we've already commented on this issue."""
    pool = get_db_pool()
    
    result = await pool.fetchrow(
        "SELECT 1 FROM bot_comments WHERE issue_external_id = $1",
        issue_external_id
    )
    
    return result is not None


async def record_comment(
    issue_external_id: str,
    comment_github_id: Optional[int] = None
) -> None:
    """Record that we've commented on an issue."""
    pool = get_db_pool()
    
    await pool.execute(
        """
        INSERT INTO bot_comments (issue_external_id, comment_github_id)
        VALUES ($1, $2)
        ON CONFLICT (issue_external_id) DO UPDATE
        SET comment_github_id = $2
        """,
        issue_external_id,
        comment_github_id
    )
    
    logger.debug("comment_recorded", extra={"issue_external_id": issue_external_id})


def format_suggestion_comment(suggestions: list[dict]) -> str:
    """
    Format suggestions as a GitHub comment.
    
    Args:
        suggestions: List of {external_id, title, score, reason}
        
    Returns:
        Markdown-formatted comment
    """
    if not suggestions:
        return ""
    
    lines = [
        "### 🔍 Possible related issues:\n",
    ]
    
    for i, sugg in enumerate(suggestions, 1):
        # Extract issue number from external_id
        # Actual format from normalize.py: "github:owner/repo#42"
        # Fallback for other formats: split by ":" or "/"
        external_id = sugg["external_id"]
        if "#" in external_id:
            issue_num = external_id.split("#")[-1]
        elif ":" in external_id:
            issue_num = external_id.split(":")[-1]
        else:
            issue_num = external_id.split("/")[-1]
        
        line = (
            f"{i}. **[{sugg['title']}](#{issue_num})** "
            f"→ {sugg['reason']}"
        )
        lines.append(line)
    
    lines.append("\n_This is an automated suggestion. Please review before marking as duplicate._")
    
    return "\n".join(lines)


# Placeholder for real GitHub API integration
# In production, this would use PyGithub or similar
async def post_comment_to_github(
    repo: str,
    issue_number: int,
    comment_text: str,
    github_token: str
) -> Optional[int]:
    """
    Post comment to GitHub issue (placeholder for real implementation).
    
    In Week 3, this would be replaced with real GitHub API call.
    For now, returns a fake comment ID.
    
    Args:
        repo: Repository (owner/name)
        issue_number: Issue number
        comment_text: Comment markdown
        github_token: GitHub API token
        
    Returns:
        GitHub comment ID if successful, None otherwise
    """
    # Placeholder: in production, use PyGithub:
    # g = Github(github_token)
    # repo_obj = g.get_repo(repo)
    # issue = repo_obj.get_issue(issue_number)
    # comment = issue.create_comment(comment_text)
    # return comment.id
    
    logger.info(
        "comment_posted_placeholder",
        extra={
            "repo": repo,
            "issue_number": issue_number,
            "comment_length": len(comment_text)
        }
    )
    
    # Return placeholder ID
    return 999999999


async def maybe_comment_with_suggestions(
    issue_id: int,
    external_id: str,
    repo: str,
    issue_number: int,
    suggestions: list[dict],
    github_token: Optional[str] = None
) -> bool:
    """
    Safely post comment with suggestions if not already done.
    
    Args:
        issue_id: Internal issue ID
        external_id: External issue ID
        repo: Repository name
        issue_number: Issue number in repo
        suggestions: List of suggestion dicts
        github_token: GitHub API token
        
    Returns:
        True if comment was posted, False if skipped (already exists)
    """
    # Gate 1: Check idempotency
    already_commented = await has_comment(external_id)
    if already_commented:
        logger.debug("skipping_comment_already_posted", extra={"issue_external_id": external_id})
        return False
    
    # Gate 2: Only comment if we have suggestions
    if not suggestions:
        logger.debug("no_suggestions_to_post", extra={"issue_external_id": external_id})
        return False
    
    # Format comment
    comment_text = format_suggestion_comment(suggestions)
    
    # Post to GitHub (or log for now)
    if github_token:
        comment_id = await post_comment_to_github(
            repo=repo,
            issue_number=issue_number,
            comment_text=comment_text,
            github_token=github_token
        )
    else:
        logger.warning("github_token_not_provided", extra={"issue_external_id": external_id})
        comment_id = None
    
    # Record in DB
    await record_comment(external_id, comment_id)
    
    logger.info(
        "suggestion_comment_posted",
        extra={
            "issue_external_id": external_id,
            "suggestion_count": len(suggestions),
            "comment_id": comment_id
        }
    )
    
    return True
