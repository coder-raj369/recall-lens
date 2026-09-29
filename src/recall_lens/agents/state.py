"""State shared by the recall-check graph. Values stay JSON-like so checkpoints can store them."""

from typing import TypedDict

AFFECTED = "affected"
NOT_AFFECTED = "not_affected"
NEEDS_INFO = "needs_info"  # the recall applies to specific units; we lack the code to tell
UNDETERMINED = "undetermined"  # rules could not decide; only arbitration or a person can
VERDICTS = (AFFECTED, NOT_AFFECTED, NEEDS_INFO, UNDETERMINED)


class Candidate(TypedDict):
    recall_id: int
    agency: str
    source_id: str
    title: str
    source_url: str | None


class Verdict(TypedDict):
    source_id: str
    agency: str
    verdict: str
    reason: str  # one sentence a person can check against the notice
    evidence: str | None  # text quoted from the recall notice
    method: str  # "rules", "llm" or "none"


class CheckState(TypedDict, total=False):
    query: str  # what the user typed; may be empty when a photo is given
    photo: str | None  # path or URL of a product photo
    identifiers: list[list[str]]  # [kind, value] pairs from the query and the photo
    codes: list[str]  # every code-like value, kind unknown
    search_text: str  # query sent to retrieval
    candidates: list[Candidate]
    verdicts: list[Verdict]
    answer: dict  # final verdict, cited recall and message
