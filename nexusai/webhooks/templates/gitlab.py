"""NexusAI Webhooks — GitLab webhook payload parser."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Normalized event keys:
#   event_type, repo, branch, author, message, url


def parse_gitlab_webhook(headers: dict, payload: dict) -> dict | None:
    """Parse a GitLab webhook request into a normalized event dict.

    Handles:
    - Push Hook
    - Merge Request Hook
    - Pipeline Hook
    - Note Hook (comments)

    Returns None for unrecognised or malformed payloads.
    """
    object_kind = payload.get("object_kind", "")
    event_name = (
        headers.get("X-Gitlab-Event")
        or headers.get("x-gitlab-event")
        or ""
    )

    try:
        if object_kind == "push" or "Push Hook" in event_name:
            return _parse_push(payload)
        if object_kind == "merge_request" or "Merge Request Hook" in event_name:
            return _parse_merge_request(payload)
        if object_kind == "pipeline" or "Pipeline Hook" in event_name:
            return _parse_pipeline(payload)
        if object_kind == "note" or "Note Hook" in event_name:
            return _parse_note(payload)
    except (KeyError, TypeError, AttributeError) as exc:
        logger.warning("Failed to parse GitLab %r webhook: %s", object_kind or event_name, exc)
        return None

    logger.debug("Unhandled GitLab event: object_kind=%r event=%r", object_kind, event_name)
    return None


# ── per-event helpers ─────────────────────────────────────────────


def _parse_push(payload: dict) -> dict:
    commits = payload.get("commits", [])
    head = commits[-1] if commits else {}
    project = payload.get("project", {})
    return {
        "event_type": "push",
        "repo": project.get("path_with_namespace", payload.get("repository", {}).get("name", "")),
        "branch": payload.get("ref", "").replace("refs/heads/", ""),
        "author": payload.get("user_name", head.get("author", {}).get("name", "")),
        "message": head.get("message", ""),
        "url": payload.get("compare", head.get("url", "")),
    }


def _parse_merge_request(payload: dict) -> dict:
    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})
    state = attrs.get("state", "")
    action = attrs.get("action", state)
    return {
        "event_type": f"merge_request.{action}",
        "repo": project.get("path_with_namespace", ""),
        "branch": attrs.get("source_branch", ""),
        "author": payload.get("user", {}).get("name", ""),
        "message": attrs.get("title", ""),
        "url": attrs.get("url", ""),
    }


def _parse_pipeline(payload: dict) -> dict:
    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})
    return {
        "event_type": "pipeline",
        "repo": project.get("path_with_namespace", ""),
        "branch": attrs.get("ref", ""),
        "author": payload.get("user", {}).get("name", ""),
        "message": f"Pipeline {attrs.get('id', '')} — {attrs.get('status', '')}",
        "url": attrs.get("url", ""),
    }


def _parse_note(payload: dict) -> dict:
    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})
    return {
        "event_type": "note",
        "repo": project.get("path_with_namespace", ""),
        "branch": "",
        "author": payload.get("user", {}).get("name", ""),
        "message": attrs.get("note", ""),
        "url": attrs.get("url", ""),
    }
