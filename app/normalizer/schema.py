from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IssueSignals(BaseModel):
    error_messages: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    stack_trace: Optional[str] = None
    has_stack_trace: bool = False
    signal_strength: float = 0.0


class NormalizedIssue(BaseModel):
    external_id: str
    repo: str
    issue_number: int
    title: str
    body: str
    clean_body: str
    labels: list[str]
    author: str
    state: str
    created_at: datetime
    updated_at: datetime
    signals: IssueSignals
    raw_payload: dict
