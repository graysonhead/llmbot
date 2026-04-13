# Copyright (C) 2024 Grayson Head <grayson@graysonhead.net>
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.
"""Read-only IMAP tools for accessing email (e.g. Fastmail)."""

import email
import email.header
import imaplib
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_IMAP_HOST = "imap.fastmail.com"
_DEFAULT_IMAP_PORT = 993


def _decode_header(value: str | bytes | None) -> str:
    """Decode an RFC 2047-encoded email header value to a plain string.

    Args:
        value: Raw header value, may be encoded.

    Returns:
        Decoded UTF-8 string, or empty string if value is None.
    """
    if value is None:
        return ""
    parts = email.header.decode_header(str(value))
    decoded_parts = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _get_connection() -> imaplib.IMAP4_SSL:
    """Open a read-only SSL IMAP connection using environment variables.

    Reads ``IMAP_HOST`` (default ``imap.fastmail.com``), ``IMAP_PORT``
    (default ``993``), ``IMAP_USER``, and ``IMAP_PASSWORD``.

    Returns:
        An authenticated :class:`imaplib.IMAP4_SSL` connection.

    Raises:
        ValueError: If ``IMAP_USER`` or ``IMAP_PASSWORD`` are not set.
    """
    host = os.environ.get("IMAP_HOST", _DEFAULT_IMAP_HOST)
    port = int(os.environ.get("IMAP_PORT", str(_DEFAULT_IMAP_PORT)))
    user = os.environ.get("IMAP_USER", "")
    password = os.environ.get("IMAP_PASSWORD", "")
    missing = [
        name
        for name, val in [("IMAP_USER", user), ("IMAP_PASSWORD", password)]
        if not val
    ]
    if missing:
        msg = f"Missing IMAP environment variables: {', '.join(missing)}"
        raise ValueError(msg)
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(user, password)
    return conn


def imap_list_mailboxes() -> str:
    """List all mailboxes (folders) available on the IMAP server.

    Returns:
        Formatted string listing mailbox names, or an error message.
    """
    try:
        conn = _get_connection()
        try:
            status, data = conn.list()
            if status != "OK" or not data:
                return "No mailboxes found."
            names = []
            for item in data:
                if item is None:
                    continue
                raw = item.decode() if isinstance(item, bytes) else str(item)
                # Format: (\Flags) "delimiter" "Name"
                parts = raw.split('"')
                if len(parts) >= 3:  # noqa: PLR2004
                    names.append(
                        parts[-2]
                        if parts[-1].strip() == ""
                        else parts[-1].strip().strip('"')
                    )
                else:
                    names.append(raw)
            return "Mailboxes:\n" + "\n".join(f"  - {n}" for n in names)
        finally:
            conn.logout()
    except ValueError as e:
        return f"IMAP configuration error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error listing mailboxes: {e}"


def imap_search_emails(  # noqa: C901, PLR0912, PLR0913
    mailbox: str = "INBOX",
    subject: str = "",
    sender: str = "",
    since: str = "",
    before: str = "",
    unseen_only: bool = False,  # noqa: FBT001, FBT002
    limit: int = 20,
) -> str:
    """Search for emails in a mailbox and return a summary of matches.

    Args:
        mailbox: Mailbox (folder) to search. Defaults to ``INBOX``.
        subject: Filter by subject text (case-insensitive substring).
        sender: Filter by sender address (case-insensitive substring).
        since: Return only emails on or after this date, format ``DD-Mon-YYYY``
            e.g. ``01-Jan-2025``.
        before: Return only emails before this date, same format as ``since``.
        unseen_only: If ``True``, return only unread messages.
        limit: Maximum number of results to return (default 20).

    Returns:
        Formatted string with email summaries (UID, date, from, subject),
        or an error message.
    """
    try:
        conn = _get_connection()
        try:
            conn.select(mailbox, readonly=True)
            criteria: list[str] = []
            if unseen_only:
                criteria.append("UNSEEN")
            if since:
                criteria.append(f"SINCE {since}")
            if before:
                criteria.append(f"BEFORE {before}")
            if subject:
                criteria.append(f'SUBJECT "{subject}"')
            if sender:
                criteria.append(f'FROM "{sender}"')
            search_str = " ".join(criteria) if criteria else "ALL"
            status, data = conn.search(None, search_str)
            if status != "OK":
                return f"Search failed: {data}"
            uid_list = data[0].split() if data[0] else []
            if not uid_list:
                return f"No emails found in '{mailbox}' matching criteria."
            # Take the most recent `limit` results (UIDs are in ascending order)
            uid_list = uid_list[-limit:]
            uid_str = ",".join(u.decode() for u in uid_list)
            fetch_status, fetch_data = conn.fetch(
                uid_str, "(FLAGS BODY[HEADER.FIELDS (DATE FROM SUBJECT)])"
            )
            if fetch_status != "OK":
                return f"Fetch failed: {fetch_data}"
            lines = [f"Emails in '{mailbox}' (showing up to {limit}):"]
            for item in fetch_data:
                if not isinstance(item, tuple):
                    continue
                meta = item[0] if isinstance(item[0], bytes) else item[0].encode()
                uid = meta.split()[0].decode()
                flags = imaplib.ParseFlags(meta)
                read_status = "READ" if rb"\Seen" in flags else "UNREAD"
                raw_headers = (
                    item[1] if isinstance(item[1], bytes) else item[1].encode()
                )
                msg = email.message_from_bytes(raw_headers)
                date = _decode_header(msg.get("Date", ""))
                sender_hdr = _decode_header(msg.get("From", ""))
                subject_hdr = _decode_header(msg.get("Subject", "(no subject)"))
                lines.append(
                    f"  [{uid}] [{read_status}] {date} | From: {sender_hdr} | {subject_hdr}"
                )
            return "\n".join(lines)
        finally:
            conn.logout()
    except ValueError as e:
        return f"IMAP configuration error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error searching emails: {e}"


def imap_get_email(uid: str, mailbox: str = "INBOX") -> str:
    """Fetch the full content of an email by its sequence number.

    Args:
        uid: Message sequence number as returned by :func:`imap_search_emails`.
        mailbox: Mailbox containing the message. Defaults to ``INBOX``.

    Returns:
        Formatted string with headers and body, or an error message.
    """
    try:
        conn = _get_connection()
        try:
            conn.select(mailbox, readonly=True)
            status, data = conn.fetch(uid, "(RFC822)")
            if status != "OK" or not data or data[0] is None:
                return f"Email {uid!r} not found in '{mailbox}'."
            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            if not isinstance(raw, bytes):
                raw = str(raw).encode()
            msg = email.message_from_bytes(raw)
            date = _decode_header(msg.get("Date", ""))
            sender = _decode_header(msg.get("From", ""))
            to = _decode_header(msg.get("To", ""))
            subject = _decode_header(msg.get("Subject", "(no subject)"))
            body = _extract_body(msg)
            _max_body = 4000
            if len(body) > _max_body:
                body = body[:_max_body] + "\n[truncated]"
            return (
                f"UID: {uid}\n"
                f"Date: {date}\n"
                f"From: {sender}\n"
                f"To: {to}\n"
                f"Subject: {subject}\n"
                f"\n{body}"
            )
        finally:
            conn.logout()
    except ValueError as e:
        return f"IMAP configuration error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error fetching email {uid!r}: {e}"


def _extract_body(msg: email.message.Message) -> str:  # noqa: C901
    """Extract plain-text body from an email message.

    Prefers ``text/plain`` parts; falls back to ``text/html`` if none exist.

    Args:
        msg: Parsed email message object.

    Returns:
        Decoded body text string.
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            text = payload.decode(charset, errors="replace")
            if ct == "text/plain":
                plain_parts.append(text)
            elif ct == "text/html":
                html_parts.append(text)
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/plain":
                plain_parts.append(text)
            else:
                html_parts.append(text)

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        # Very basic HTML strip — just remove tags
        import re  # noqa: PLC0415

        combined = "\n".join(html_parts)
        return re.sub(r"<[^>]+>", "", combined)
    return "(no body)"


IMAP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "imap_list_mailboxes",
            "description": "List all mailboxes (folders) available on the IMAP email server",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "imap_search_emails",
            "description": (
                "Search for emails in a mailbox and return a summary of matches. "
                "Returns sequence numbers that can be passed to imap_get_email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {
                        "type": "string",
                        "description": "Mailbox to search (default: INBOX)",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Filter by subject text (case-insensitive substring)",
                    },
                    "sender": {
                        "type": "string",
                        "description": "Filter by sender address (case-insensitive substring)",
                    },
                    "since": {
                        "type": "string",
                        "description": "Return emails on or after this date, format DD-Mon-YYYY e.g. 01-Jan-2025",
                    },
                    "before": {
                        "type": "string",
                        "description": "Return emails before this date, format DD-Mon-YYYY e.g. 31-Jan-2025",
                    },
                    "unseen_only": {
                        "type": "boolean",
                        "description": "If true, return only unread messages",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 20)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "imap_get_email",
            "description": "Fetch the full content of an email by its sequence number (from imap_search_emails)",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "Message sequence number as returned by imap_search_emails",
                    },
                    "mailbox": {
                        "type": "string",
                        "description": "Mailbox containing the message (default: INBOX)",
                    },
                },
                "required": ["uid"],
            },
        },
    },
]

IMAP_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "imap_list_mailboxes": imap_list_mailboxes,
    "imap_search_emails": imap_search_emails,
    "imap_get_email": imap_get_email,
}
