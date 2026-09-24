# ADR-0003: Verify matches deterministically before consulting an LLM

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Whether a recall applies to a specific unit usually depends on structured facts: a lot code within a range, a production date inside a window, a model number with a particular suffix, a VIN in an affected build range. Language models are unreliable at exactly this kind of comparison, and their errors are silent.

The cost of errors is asymmetric. Telling a user a recalled product is safe (a false negative) can cause real harm; flagging a safe product as possibly recalled costs the user a minute of checking.

## Decision

Verification runs in two stages:

1. **Deterministic checks.** Parsed identifiers are compared against the recall's identifiers and ranges in code. A definitive rule result (match or clear non-match) is final.
2. **LLM arbitration.** Only cases the rules cannot decide (missing fields, free-text scope such as "all lots sold before March") go to the LLM, which must cite the recall text and return a confidence score.

The advisor **abstains** whenever the final confidence is below a threshold, and asks for more evidence (a clearer photo of the lot code, the model year) instead of answering. The threshold is tuned on the evaluation set to minimize false negatives at an acceptable abstention rate.

## Consequences

- The most common and most important cases are decided by testable code, not by prompts.
- Every "not recalled" answer is traceable to either a rule or a cited LLM judgment.
- Abstention rate becomes a reported metric alongside false-negative rate, precision and recall.
- Rule coverage must grow with the variety of identifier formats in the corpus; Phase 1 extraction and Phase 4 verification carry that cost.
