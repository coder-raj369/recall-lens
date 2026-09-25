"""Attach text-extracted identifiers to recalls before they are stored."""

from dataclasses import replace

from recall_lens.extract import rules
from recall_lens.ingest.models import Recall


def enrich(recall: Recall, use_model: bool = True) -> Recall:
    """Add identifiers found in the title and description to those the agency supplied."""
    text = "\n".join(filter(None, [recall.title, recall.description]))
    found = rules.extract(text)
    if use_model:
        from recall_lens.extract import model

        found |= model.extract(text)
    return replace(recall, identifiers=recall.identifiers | found)
