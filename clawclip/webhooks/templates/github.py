"""ClawClip Webhooks — GitHub webhook payload parser."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Normalized event keys returned by this module:
#   event_type, repo, branch, author, message, url


def parse_github_webhook(headers: dict, payload: dict) -> dict | None:
    """Parse a GitHub webhook request into a normalized event dict.

    Handles:
    - push
    - pull_request.opened / pull_request.closed
    - issues.opened
    - workflow_run.completed

    Returns None when the event type is unrecognised or the payload is
    malformed, so callers can decide how to respond (e.g. return HTTP 200
    without processing).
    """
    event = headers.get("X-GitHub-Event") or headers.get("x-github-event", "")

    try:
        if event == "push":
            return _parse_push(payload)
        if event == "pull_request":
            return _parse_pull_request(payload)
        if event == "issues":
            return _parse_issues(payload)
        if event == "workflow_run":
            return _parse_workflow_run(payload)
    except (KeyError, TypeError, AttributeError) as exc:
        logger.warning("Failed to parse GitHub %r webhook: %s", event, exc)
        return None

    logger.debug("Unhandled GitHub event type: %r", event)
    return None


# ── per-event helpers ─────────────────────────────────────────────


def _parse_push(payload: dict) -> dict:
    repo = payload.get("repository", {})
    commits = payload.get("commits", [])
    head = commits[-1] if commits else {}
    return {
        "event_type": "push",
        "repo": repo.get("full_name", ""),
        "branch": payload.get("ref", "").replace("refs/heads/", ""),
        "author": head.get("author", {}).get("name", ""),
        "message": head.get("message", ""),
        "url": payload.get("compare", ""),
    }


def _parse_pull_request(payload: dict) -> dict | None:
    action = payload.get("action", "")
    if action not in {"opened", "closed"}:
        return None
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    return {
        "event_type": f"pull_request.{action}",
        "repo": repo.get("full_name", ""),
        "branch": pr.get("head", {}).get("ref", ""),
        "author": pr.get("user", {}).get("login", ""),
        "message": pr.get("title", ""),
        "url": pr.get("html_url", ""),
    }


def _parse_issues(payload: dict) -> dict | None:
    action = payload.get("action", "")
    if action != "opened":
        return None
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})
    return {
        "event_type": "issues.opened",
        "repo": repo.get("full_name", ""),
        "branch": "",
        "author": issue.get("user", {}).get("login", ""),
        "message": issue.get("title", ""),
        "url": issue.get("html_url", ""),
    }


def _parse_workflow_run(payload: dict) -> dict | None:
    action = payload.get("action", "")
    if action != "completed":
        return None
    run = payload.get("workflow_run", {})
    repo = payload.get("repository", {})
    return {
        "event_type": "workflow_run.completed",
        "repo": repo.get("full_name", ""),
        "branch": run.get("head_branch", ""),
        "author": run.get("triggering_actor", {}).get("login", ""),
        "message": f"{run.get('name', '')} — {run.get('conclusion', '')}",
        "url": run.get("html_url", ""),
    }
