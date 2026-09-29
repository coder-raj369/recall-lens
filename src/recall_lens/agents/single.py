"""Single-agent baseline (ADR-0002): Claude with a search tool, and no graph or rules.

Claude searches the recall corpus itself, reads the notices it finds and gives the verdict. The
end-to-end evaluation compares it with the multi-agent graph to show what the graph's structure
and deterministic checks add. Off by default: every call is billed.
"""

from typing import Literal

import anthropic
import psycopg
from pydantic import BaseModel, Field, ValidationError

from recall_lens.agents.arbitrate import FALLBACK_BETA, MODEL
from recall_lens.agents.nodes import load_scope
from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NO_MATCH, NOT_AFFECTED
from recall_lens.retrieval import search as retrieval

SYSTEM = """\
You help a consumer find out whether a product they own has been recalled in the US. Search the
recall notices with the search_recalls tool, as often as useful (by brand, by product, by a code
they gave), read the scope of the notices you find, and answer:
- affected: a notice covers their unit, either every unit or a code, date or model year they gave.
- not_affected: a notice is about their product, but what they gave is outside its scope.
- needs_info: a notice may cover their product, but deciding needs something they have not given.
- no_match: no notice you found is about their product.
A wrong "not_affected" or "no_match" can leave someone using a dangerous product, so answer
needs_info when the evidence is thin. Cite the notice your answer rests on and quote it exactly."""

TOOL = {
    "name": "search_recalls",
    "description": "Search CPSC, FDA and NHTSA recall notices. Returns the five closest notices "
    "with their recall number and the start of their text, where the scope is stated.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words or codes to search for."}},
        "required": ["query"],
    },
}
NOTICE_CHARS = 3_000


class Answer(BaseModel):
    recall: str | None = Field(description='The notice the answer rests on, as "agency:number".')
    quote: str = Field(description="A passage copied exactly from that notice, or empty.")
    reason: str = Field(description="One sentence the consumer can check against the notice.")
    verdict: Literal["affected", "not_affected", "needs_info", "no_match"]


VERDICTS = {
    "affected": AFFECTED,
    "not_affected": NOT_AFFECTED,
    "needs_info": NEEDS_INFO,
    "no_match": NO_MATCH,
}


def search_tool(conn: psycopg.Connection, query: str, search=retrieval.search) -> str:
    notices = [
        f'<notice recall="{h.agency}:{h.source_id}">\n'
        f"{load_scope(conn, h.recall_id).text[:NOTICE_CHARS]}\n</notice>"
        for h in search(conn, query, limit=5)
    ]
    return "\n".join(notices) or "No recalls found."


def check(
    client: anthropic.Anthropic,
    conn: psycopg.Connection,
    text: str,
    search=retrieval.search,
    max_searches: int = 4,
) -> tuple[str, str | None, str]:
    """Claude's (verdict, cited recall, reason) for what the person said or showed."""
    messages = [{"role": "user", "content": f"<consumer>\n{text}\n</consumer>"}]
    schema = anthropic.transform_schema(Answer)
    try:
        for _ in range(max_searches + 1):
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=messages,
                tools=[TOOL],
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "high",
                    "format": {"type": "json_schema", "schema": schema},
                },
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            if response.stop_reason != "tool_use":
                break
            results = [
                {"type": "tool_result", "tool_use_id": block.id,
                 "content": search_tool(conn, block.input["query"], search)}
                for block in response.content
                if block.type == "tool_use"
            ]  # fmt: skip
            messages += [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": results},
            ]
    except anthropic.APIError as error:
        return NEEDS_INFO, None, f"Claude was unavailable ({type(error).__name__})."
    if response.stop_reason == "refusal":
        return NEEDS_INFO, None, "Claude declined to answer."
    try:
        answer = Answer.model_validate_json(
            next(block.text for block in response.content if block.type == "text")
        )
    except (StopIteration, ValidationError):
        return NEEDS_INFO, None, "Claude's answer was incomplete or malformed."
    return VERDICTS[answer.verdict], answer.recall, answer.reason
