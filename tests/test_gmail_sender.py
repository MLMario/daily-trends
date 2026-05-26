"""Behavior tests for scripts.lib.gmail_sender.GmailSender.

Unit tests exercise MIME assembly in isolation (no network). The integration
test creates a real draft via the Gmail API and deletes it on teardown; it
skips cleanly when OAuth credentials are absent.
"""

from __future__ import annotations

import email
import json
from email.message import Message
from pathlib import Path

import pytest

from scripts.lib.gmail_sender import Attachment, GmailSender

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = REPO_ROOT / "credentials" / "token.json"
CLIENT_FILE = REPO_ROOT / "credentials" / "oauth_client.json"


def parse_mime(raw: bytes) -> Message:
    return email.message_from_bytes(raw)


def parts_by_filename(msg: Message) -> dict[str, Message]:
    out: dict[str, Message] = {}
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        if name:
            out[name] = part
    return out


def test_build_mime_has_to_and_subject_headers() -> None:
    raw = GmailSender.build_mime(
        to="mariogj1987@gmail.com",
        subject="[daily-trends] Run 2026-05-26T10-00Z",
        html_body="<p>hi</p>",
        attachments=[],
    )

    msg = parse_mime(raw)
    assert msg["To"] == "mariogj1987@gmail.com"
    assert msg["Subject"] == "[daily-trends] Run 2026-05-26T10-00Z"


def test_build_mime_includes_html_body_part() -> None:
    raw = GmailSender.build_mime(
        to="x@example.com",
        subject="s",
        html_body="<p>greetings &amp; salutations</p>",
        attachments=[],
    )

    msg = parse_mime(raw)
    html_parts = [p for p in msg.walk() if p.get_content_type() == "text/html"]
    assert len(html_parts) == 1
    body = html_parts[0].get_payload(decode=True).decode("utf-8")
    assert "<p>greetings &amp; salutations</p>" in body


def test_build_mime_attaches_json_files_with_correct_filenames() -> None:
    raw = GmailSender.build_mime(
        to="x@example.com",
        subject="s",
        html_body="<p>hi</p>",
        attachments=[
            Attachment(filename="corpus.json", content=b'{"k":1}'),
            Attachment(filename="errors.log", content=b'{"step":"x"}\n'),
        ],
    )

    msg = parse_mime(raw)
    parts = parts_by_filename(msg)
    assert set(parts) == {"corpus.json", "errors.log"}
    assert parts["corpus.json"].get_payload(decode=True) == b'{"k":1}'


def test_build_mime_is_multipart_mixed_when_attachments_present() -> None:
    raw = GmailSender.build_mime(
        to="x@example.com",
        subject="s",
        html_body="<p>hi</p>",
        attachments=[Attachment(filename="a.json", content=b"{}")],
    )

    msg = parse_mime(raw)
    assert msg.get_content_type() == "multipart/mixed"


# ----- integration -----


creds_available = TOKEN_FILE.exists() and CLIENT_FILE.exists()


@pytest.mark.skipif(
    not creds_available,
    reason="gmail OAuth credentials not present locally (credentials/token.json missing)",
)
def test_draft_mode_creates_and_cleans_up_a_real_gmail_draft(tmp_path: Path) -> None:
    sender = GmailSender(client_file=CLIENT_FILE, token_file=TOKEN_FILE)
    subject = "[daily-trends] integration test draft — safe to ignore"

    result = sender.dispatch(
        mode="draft",
        to="mariogj1987@gmail.com",
        subject=subject,
        html_body="<p>integration test — auto-deleted after assertion</p>",
        attachments=[],
    )

    assert result.ok
    assert result.mode == "draft"
    assert result.id

    drafts = sender.list_drafts()
    try:
        assert any(d["id"] == result.id for d in drafts)
    finally:
        sender.delete_draft(result.id)
