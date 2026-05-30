"""Render and dispatch the run's email.

Usage: python -m scripts.send_email <run_id>

Reads config.json from repo root; honors `email_to` and `email_mode`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.lib.email_renderer import EmailRenderer
from scripts.lib.error_log import ErrorLog
from scripts.lib.gmail_sender import Attachment, GmailSender
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
CONFIG = REPO_ROOT / "config.json"
CREDS = REPO_ROOT / "credentials"


def gather_attachments(workspace: RunWorkspace) -> list[Attachment]:
    """Per-run artifacts to ride along with the Digest email.

    Each path is guarded by an existence check, so a slow day (no synthesis
    files) or a failed report step simply omits the attachment with no special
    casing — report.html joins the same guarded list as the synthesis JSON.
    """
    candidates = (
        workspace.trending_topics,
        workspace.content_recommendations,
        workspace.report,
    )
    return [
        Attachment(filename=path.name, content=path.read_bytes())
        for path in candidates
        if path.exists()
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.send_email <run_id>", file=sys.stderr)
        return 2

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    workspace = RunWorkspace.existing_run(RUNS_ROOT, argv[1])
    log = ErrorLog(workspace.errors)

    renderer = EmailRenderer(workspace)
    html_body = renderer.render(run_id=workspace.run_id)

    attachments = gather_attachments(workspace)

    sender = GmailSender(
        client_file=CREDS / "oauth_client.json",
        token_file=CREDS / "token.json",
    )
    try:
        result = sender.dispatch(
            mode=config["email_mode"],
            to=config["email_to"],
            subject=f"[daily-trends] Run {workspace.run_id}",
            html_body=html_body,
            attachments=attachments,
        )
    except Exception as exc:
        log.log(step="dispatch", severity="error", message=str(exc))
        raise

    log.log(
        step="dispatch",
        severity="info",
        message=f"{result.mode} id={result.id}",
    )
    print(f"email outcome: mode={result.mode} id={result.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
