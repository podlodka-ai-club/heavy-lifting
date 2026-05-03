"""Stable hash over the user-authored portion of a TrackerTask.

Used by ``tracker_intake`` to detect when a tracker-side update originated
from the user (versus our own write of attachments/comments) and therefore
warrants refreshing ``fetch_task.context`` and, conditionally, the stored
``last_triage_user_content_hash`` (см. план §6.7a).

Design notes:

* References tagged ``origin='own_write'`` are excluded — they are produced
  by our adapters and must not perturb the hash. References with
  ``origin='user'`` *or* ``origin=None`` (legacy/unknown) participate in the
  hash; an unknown provenance fails safely as user-authored.
* ``metadata`` does not enter the hash — it carries our internal fields
  (selection state, estimate snapshots, last_triage_user_content_hash) and
  must not invalidate itself.
* Acceptance criteria and references are sorted to make the hash independent
  of ordering tweaks performed by the tracker UI.
"""

from __future__ import annotations

import hashlib

from backend.schemas import TrackerTask


def compute_user_content_hash(tracker_task: TrackerTask) -> str:
    user_links = sorted(
        (link.label, link.url)
        for link in tracker_task.context.references
        if link.origin != "own_write"
    )
    payload_lines: list[str] = [
        tracker_task.context.title or "",
        tracker_task.context.description or "",
        *sorted(tracker_task.context.acceptance_criteria),
        "---references---",
        *(f"{label}\t{url}" for label, url in user_links),
    ]
    payload = "\n".join(payload_lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["compute_user_content_hash"]
