"""Claude arbitration for candidates the rules left undetermined (ADR-0003).

The rules settle codes, dates and model years. What they leave open is mostly whether a notice is
about the user's product at all: a product described in other words, a missing brand, a scope in
free text. One Claude call judges every open candidate, and each judgment must quote its notice
word for word; a judgment whose quote is not in the notice is dropped. Refusals, errors and
malformed answers leave candidates undetermined, so the advisor abstains rather than guesses.

Nothing wires this node in by default: it needs the `llm` dependency group, credentials and an
explicit opt-in, because every call is billed.
"""

from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from recall_lens.agents.nodes import Services, load_scope
from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NOT_AFFECTED, UNDETERMINED, CheckState
from recall_lens.agents.verify import Scope

MODEL = "claude-opus-5-5"
# Declined requests are re-run server-side on the model Anthropic recommends for that category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """\
You help a consumer find out whether a product they own is covered by a recall. You get what they
told us (plus any text read from a photo of the product) and recall notices that search returned.
Rule-based checks have already compared codes, dates and model years against these notices and
could not decide, usually because it is unclear whether a notice is about the consumer's product.

Judge each notice:
- affected: it is about the consumer's product and covers their unit, either every unit or a code,
  date or model year they gave.
- not_affected: it is about their product, but a code, date or model year they gave is outside the
  scope it states.
- needs_info: it may cover their product, but deciding needs something they have not given, such
  as the brand, a model or lot number, a date or a model year. Name it in the reason.
- unrelated: it is about a different product.

A wrong "not_affected" or "unrelated" can leave someone using a dangerous product, while a wrong
"needs_info" costs them a minute, so choose needs_info when the evidence is thin, and do not assume
facts the consumer did not give. For each notice, quote one passage copied exactly from it
(contiguous, no ellipses) that supports your verdict, give one sentence of reasoning the consumer
can check against the notice, and your confidence from 0 to 1 that the verdict is right."""


class Judgment(BaseModel):
    notice: int = Field(description="The id of the notice judged.")
    quote: str = Field(description="A passage copied exactly from that notice.")
    reason: str = Field(description="One sentence the consumer can check against the notice.")
    verdict: Literal["affected", "not_affected", "needs_info", "unrelated"]
    confidence: float = Field(ge=0, le=1)


class Judgments(BaseModel):
    judgments: list[Judgment]


_VERDICTS = {
    "affected": AFFECTED,
    "not_affected": NOT_AFFECTED,
    "needs_info": NEEDS_INFO,
    "unrelated": UNDETERMINED,  # skipped by the advisor, like any recall not tied to the product
}


def notice(scope: Scope) -> str:
    """A recall as Claude reads it: title, scope text and affected vehicles."""
    vehicles = [
        f"{v.make} {v.model} ({', '.join(map(str, sorted(v.years))) if v.years else 'all years'})"
        for v in scope.vehicles
    ]
    return "\n".join([scope.text, *vehicles])


def _flat(text: str) -> str:
    return " ".join(text.split()).casefold()


def _unusable(reason: str) -> dict:
    return {"verdict": UNDETERMINED, "reason": reason, "evidence": None, "confidence": None}


def judge(client: anthropic.Anthropic, state: CheckState, notices: list[str]) -> list[dict]:
    """Claude's cited verdict for each notice, in order; undetermined wherever it is unusable."""
    identifiers = "\n".join(f"{kind}: {value}" for kind, value in state.get("identifiers", []))
    prompt = f"<consumer>\n{state.get('text', '')}\n</consumer>\n" + (
        f"<identifiers>\n{identifiers}\n</identifiers>\n" if identifiers else ""
    )
    prompt += "".join(
        f'<notice id="{i}">\n{body}\n</notice>\n' for i, body in enumerate(notices, 1)
    )
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(Judgments)},
            },
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIError as error:
        return [_unusable(f"Claude was unavailable ({type(error).__name__}).") for _ in notices]
    if response.stop_reason == "refusal":
        return [_unusable("Claude declined to judge these recalls.") for _ in notices]
    try:
        text = next(block.text for block in response.content if block.type == "text")
        judgments = Judgments.model_validate_json(text).judgments
    except (StopIteration, ValidationError):
        return [_unusable("Claude's answer was incomplete or malformed.") for _ in notices]

    by_notice: dict[int, Judgment] = {}
    for j in judgments:
        by_notice.setdefault(j.notice, j)
    results = []
    for i, body in enumerate(notices, 1):
        j = by_notice.get(i)
        if j is None:
            results.append(_unusable("Claude did not judge this recall."))
        elif not _flat(j.quote) or _flat(j.quote) not in _flat(body):
            results.append(_unusable("Claude's quote does not appear in this notice."))
        else:
            results.append(
                {"verdict": _VERDICTS[j.verdict], "reason": j.reason, "evidence": j.quote,
                 "confidence": j.confidence}
            )  # fmt: skip
    return results


def arbitrate(services: Services, client: anthropic.Anthropic):
    """Replace the rules' undetermined verdicts with Claude's cited judgments."""

    def run(state: CheckState) -> dict:
        verdicts = list(state["verdicts"])
        open_ = [i for i, v in enumerate(verdicts) if v["verdict"] == UNDETERMINED]
        if not open_:
            return {}
        notices = [
            notice(load_scope(services.conn, state["candidates"][i]["recall_id"])) for i in open_
        ]
        for i, judged in zip(open_, judge(client, state, notices), strict=True):
            verdicts[i] = {**verdicts[i], **judged, "method": "llm"}
        return {"verdicts": verdicts}

    return run
