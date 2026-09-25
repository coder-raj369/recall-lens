"""Attach text-extracted identifiers to recalls before they are stored.

Codes come from the rules and brands from GLiNER. On the extraction dev split, letting GLiNER
add codes lowered code F1 (0.59 to 0.55) by trading precision for little recall.
"""

from dataclasses import replace

from recall_lens.extract import rules
from recall_lens.ingest.models import Recall


def enrich(recall: Recall, use_model: bool = True) -> Recall:
    """Add identifiers found in the title and description to those the agency supplied."""
    text = "\n".join(filter(None, [recall.title, recall.description]))
    found = rules.extract(text)
    if use_model:
        from recall_lens.extract import model

        found |= model.extract(text, kinds=model.BRAND_ONLY)
    return replace(recall, identifiers=recall.identifiers | found)
