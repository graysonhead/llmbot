"""SQLite-backed memory and conversation summary store for llmbot."""

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_summaries (
    channel_id    INTEGER PRIMARY KEY,
    summary       TEXT    NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    last_updated  DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS summary_history (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id                INTEGER NOT NULL,
    summary                   TEXT    NOT NULL,
    message_count_at_snapshot INTEGER NOT NULL DEFAULT 0,
    created_at                DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_summary_history_channel ON summary_history(channel_id);

CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    content       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    category      TEXT    NOT NULL DEFAULT 'note'
                      CHECK(category IN ('fact','preference','task','note','workflow')),
    created_at    DATETIME NOT NULL DEFAULT (datetime('now')),
    last_accessed DATETIME NOT NULL DEFAULT (datetime('now')),
    access_count  INTEGER  NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);

CREATE TABLE IF NOT EXISTS raw_history (
    channel_id INTEGER PRIMARY KEY,
    messages   TEXT    NOT NULL DEFAULT '[]',
    updated_at DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loops (
    id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    name           TEXT     NOT NULL,
    frequency      TEXT     NOT NULL,
    prompt         TEXT     NOT NULL,
    output_channel INTEGER  NOT NULL,
    target         TEXT     NOT NULL DEFAULT '',
    model          TEXT     NOT NULL DEFAULT '',
    timezone       TEXT     NOT NULL DEFAULT 'UTC',
    enabled        INTEGER  NOT NULL DEFAULT 1,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    last_run       DATETIME,
    next_run       DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loops_next_run ON loops(next_run, enabled);

CREATE TABLE IF NOT EXISTS tool_call_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id  INTEGER NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    tool_calls  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_call_logs_channel ON tool_call_logs(channel_id);
"""


def parse_consolidation_response(text: str) -> dict[str, Any]:
    """Parse the LLM's JSON consolidation response with multiple fallback strategies.

    Returns a dict with 'summary' (str) and 'memories' (list) keys.
    """

    def _validate(obj: object) -> dict[str, Any]:
        if not isinstance(obj, dict):
            raise TypeError
        summary = obj.get("summary", "")
        memories = obj.get("memories", [])
        return {
            "summary": summary if isinstance(summary, str) else str(summary),
            "memories": memories if isinstance(memories, list) else [],
        }

    # 1. Direct parse
    try:
        return _validate(json.loads(text.strip()))
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Strip markdown code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        try:
            return _validate(json.loads(fence_match.group(1).strip()))
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Extract first {...} block
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return _validate(json.loads(brace_match.group(0)))
        except (json.JSONDecodeError, TypeError):
            pass

    logger.warning(
        "Failed to parse consolidation response as JSON; storing raw text as summary"
    )
    return {"summary": text, "memories": []}


class MemoryStore:
    """SQLite-backed store for conversation summaries and long-term memories."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize with the path to the SQLite database file."""
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def initialize(self) -> None:
        """Create the database directory and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Migration: add timezone column to existing databases
            cols = {row[1] for row in conn.execute("PRAGMA table_info(loops)")}
            if "timezone" not in cols:
                conn.execute(
                    "ALTER TABLE loops ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'"
                )

    # ------------------------------------------------------------------
    # Conversation summaries
    # ------------------------------------------------------------------

    def get_summary(self, channel_id: int) -> str | None:
        """Return the current summary for a channel, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM conversation_summaries WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] if row else None

    def get_message_count(self, channel_id: int) -> int:
        """Return the current message count for a channel."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT message_count FROM conversation_summaries WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] if row else 0

    def increment_message_count(self, channel_id: int) -> int:
        """Increment the message count and return the new value."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_summaries(channel_id, summary, message_count)
                VALUES(?, '', 1)
                ON CONFLICT(channel_id) DO UPDATE SET message_count = message_count + 1
                """,
                (channel_id,),
            )
            row = conn.execute(
                "SELECT message_count FROM conversation_summaries WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] if row else 1

    def save_summary(
        self,
        channel_id: int,
        old_summary: str,
        new_summary: str,
    ) -> None:
        """Save a new summary, archiving the old one to summary_history first."""
        with self._connect() as conn:
            # Snapshot the old summary before overwriting
            if old_summary:
                msg_count = conn.execute(
                    "SELECT message_count FROM conversation_summaries WHERE channel_id = ?",
                    (channel_id,),
                ).fetchone()
                count_at_snapshot = msg_count[0] if msg_count else 0
                conn.execute(
                    """
                    INSERT INTO summary_history(channel_id, summary, message_count_at_snapshot)
                    VALUES(?, ?, ?)
                    """,
                    (channel_id, old_summary, count_at_snapshot),
                )

            # Write the new summary and reset message_count
            conn.execute(
                """
                INSERT INTO conversation_summaries(channel_id, summary, message_count, last_updated)
                VALUES(?, ?, 0, datetime('now'))
                ON CONFLICT(channel_id) DO UPDATE SET
                    summary = excluded.summary,
                    message_count = 0,
                    last_updated = datetime('now')
                """,
                (channel_id, new_summary),
            )

    def get_summary_history(
        self, channel_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return archived summaries for a channel, most recent first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, channel_id, summary, message_count_at_snapshot, created_at
                FROM summary_history
                WHERE channel_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "channel_id": r[1],
                "summary": r[2],
                "message_count_at_snapshot": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------

    def get_memories_for_user(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return long-term memories for a user, updating access metadata."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, content, tags, category
                FROM memories
                WHERE user_id = ?
                ORDER BY last_accessed DESC, access_count DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

            if rows:
                ids = [r[0] for r in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"""
                    UPDATE memories
                    SET last_accessed = datetime('now'), access_count = access_count + 1
                    WHERE id IN ({placeholders})
                    """,  # noqa: S608
                    ids,
                )

        return [
            {
                "id": r[0],
                "content": r[1],
                "tags": json.loads(r[2]) if r[2] else [],
                "category": r[3],
            }
            for r in rows
        ]

    def save_memories(self, memories: list[dict[str, Any]]) -> None:
        """Bulk-insert new memories."""
        if not memories:
            return
        with self._connect() as conn:
            for mem in memories:
                tags = mem.get("tags", [])
                conn.execute(
                    """
                    INSERT INTO memories(user_id, content, tags, category)
                    VALUES(?, ?, ?, ?)
                    """,
                    (
                        mem["user_id"],
                        mem["content"],
                        json.dumps(tags if isinstance(tags, list) else []),
                        mem.get("category", "note"),
                    ),
                )

    # ------------------------------------------------------------------
    # Raw message history (for cross-restart continuity)
    # ------------------------------------------------------------------

    def save_raw_history(self, channel_id: int, messages: list[dict[str, str]]) -> None:
        """Persist recent raw messages so they survive a bot restart."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_history(channel_id, messages, updated_at)
                VALUES(?, ?, datetime('now'))
                ON CONFLICT(channel_id) DO UPDATE SET
                    messages   = excluded.messages,
                    updated_at = datetime('now')
                """,
                (channel_id, json.dumps(messages)),
            )

    def get_raw_history(self, channel_id: int) -> list[dict[str, str]]:
        """Return persisted raw messages for a channel."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT messages FROM raw_history WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        if not row:
            return []
        try:
            data = json.loads(row[0])
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def clear_summary(self, channel_id: int) -> None:
        """Clear the current summary text for a channel."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversation_summaries SET summary = '', last_updated = datetime('now') WHERE channel_id = ?",
                (channel_id,),
            )

    def clear_raw_history(self, channel_id: int) -> None:
        """Delete stored recent messages for a channel."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM raw_history WHERE channel_id = ?",
                (channel_id,),
            )

    # ------------------------------------------------------------------
    # Tool call logs
    # ------------------------------------------------------------------

    def save_tool_call_log(
        self, channel_id: int, tool_calls: list[dict[str, Any]]
    ) -> int:
        """Persist a tool call log entry and return its id."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tool_call_logs(channel_id, tool_calls) VALUES(?, ?)",
                (channel_id, json.dumps(tool_calls)),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_tool_call_log(self, log_id: int) -> dict[str, Any] | None:
        """Return a tool call log entry by id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, channel_id, created_at, tool_calls FROM tool_call_logs WHERE id = ?",
                (log_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "channel_id": row[1],
            "created_at": row[2],
            "tool_calls": json.loads(row[3]),
        }

    def format_memories_for_prompt(self, memories: list[dict[str, Any]]) -> str:
        """Format memories as a block for injection into the system prompt."""
        if not memories:
            return ""
        lines = ["[Long-term memories about this user:"]
        lines.extend(f"- ({mem['category']}) {mem['content']}" for mem in memories)
        lines.append("]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------

    def create_loop(  # noqa: PLR0913
        self,
        name: str,
        frequency: str,
        prompt: str,
        output_channel: int,
        next_run: datetime,
        target: str = "",
        model: str = "",
        timezone: str = "UTC",
    ) -> int:
        """Insert a new loop and return its id.

        Args:
            name: Human-readable loop name.
            frequency: Frequency string, e.g. ``"daily@08:00"``.
            prompt: System prompt used when the loop fires.
            output_channel: Discord channel snowflake to post results to.
            next_run: UTC datetime of the first scheduled execution.
            target: Optional mention string prepended to the response.
            model: Optional model override (empty string = use bot default).
            timezone: IANA timezone name for scheduling (e.g. ``"America/Chicago"``).

        Returns:
            The auto-assigned loop id.
        """
        next_run_str = next_run.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO loops(name, frequency, prompt, output_channel,
                                  target, model, timezone, next_run)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    frequency,
                    prompt,
                    output_channel,
                    target,
                    model,
                    timezone,
                    next_run_str,
                ),
            )
        return cursor.lastrowid or 0

    def get_loop(self, loop_id: int) -> dict[str, Any] | None:
        """Return a single loop row as a dict, or None if not found.

        Args:
            loop_id: The loop's primary key.

        Returns:
            A dict of loop fields, or None.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, frequency, prompt, output_channel, target, "
                "model, timezone, enabled, created_at, last_run, next_run FROM loops WHERE id = ?",
                (loop_id,),
            ).fetchone()
        return _row_to_loop(row) if row else None

    def list_loops(self) -> list[dict[str, Any]]:
        """Return all loop rows as a list of dicts ordered by id."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, frequency, prompt, output_channel, target, "
                "model, timezone, enabled, created_at, last_run, next_run FROM loops ORDER BY id",
            ).fetchall()
        return [_row_to_loop(r) for r in rows]

    def update_loop(self, loop_id: int, **fields: int | str) -> bool:
        """Update arbitrary fields on a loop row.

        Args:
            loop_id: The loop's primary key.
            **fields: Column names and new values to set.

        Returns:
            True if a row was updated, False if the id was not found.
        """
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = [*fields.values(), loop_id]
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE loops SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
        return cursor.rowcount > 0

    def delete_loop(self, loop_id: int) -> bool:
        """Delete a loop by id.

        Args:
            loop_id: The loop's primary key.

        Returns:
            True if a row was deleted, False if the id was not found.
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM loops WHERE id = ?", (loop_id,))
        return cursor.rowcount > 0

    def get_due_loops(self, now: datetime) -> list[dict[str, Any]]:
        """Return enabled loops whose next_run is at or before now.

        Args:
            now: Current UTC datetime used for comparison.

        Returns:
            List of loop dicts that are ready to fire.
        """
        now_str = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, frequency, prompt, output_channel, target, "
                "model, timezone, enabled, created_at, last_run, next_run FROM loops "
                "WHERE enabled = 1 AND next_run <= ?",
                (now_str,),
            ).fetchall()
        return [_row_to_loop(r) for r in rows]

    def get_all_memories(self) -> list[dict[str, Any]]:
        """Return all memories ordered by user_id then last_accessed descending."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, content, tags, category,
                       created_at, last_accessed, access_count
                FROM memories
                ORDER BY user_id, last_accessed DESC
                """,
            ).fetchall()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "content": r[2],
                "tags": json.loads(r[3]) if r[3] else [],
                "category": r[4],
                "created_at": r[5],
                "last_accessed": r[6],
                "access_count": r[7],
            }
            for r in rows
        ]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        """Return a single memory by id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, content, tags, category,
                       created_at, last_accessed, access_count
                FROM memories WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "content": row[2],
            "tags": json.loads(row[3]) if row[3] else [],
            "category": row[4],
            "created_at": row[5],
            "last_accessed": row[6],
            "access_count": row[7],
        }

    def update_memory(
        self,
        memory_id: int,
        content: str,
        tags: list[str],
        category: str,
    ) -> bool:
        """Update content, tags, and category of a memory.

        Returns:
            True if a row was updated, False if id not found.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE memories SET content = ?, tags = ?, category = ? WHERE id = ?",
                (content, json.dumps(tags), category, memory_id),
            )
        return cursor.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory by id.

        Returns:
            True if a row was deleted, False if id not found.
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def create_memory(
        self,
        user_id: int,
        content: str,
        tags: list[str],
        category: str,
    ) -> int:
        """Insert a new memory and return its id.

        Args:
            user_id: Discord user snowflake.
            content: The memory text.
            tags: List of keyword tags.
            category: One of fact, preference, task, note, workflow.

        Returns:
            The auto-assigned memory id.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories(user_id, content, tags, category) VALUES(?, ?, ?, ?)",
                (user_id, content, json.dumps(tags), category),
            )
        return cursor.lastrowid or 0

    def get_all_channel_summaries(self) -> list[dict[str, Any]]:
        """Return all channel summary rows ordered by last_updated descending."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT channel_id, summary, message_count, last_updated
                FROM conversation_summaries
                ORDER BY last_updated DESC
                """,
            ).fetchall()
        return [
            {
                "channel_id": r[0],
                "summary": r[1],
                "message_count": r[2],
                "last_updated": r[3],
            }
            for r in rows
        ]

    def update_loop_run(
        self, loop_id: int, last_run: datetime, next_run: datetime
    ) -> None:
        """Persist last_run and next_run timestamps after a loop executes.

        Args:
            loop_id: The loop's primary key.
            last_run: UTC datetime of the execution that just completed.
            next_run: UTC datetime of the next scheduled execution.
        """
        last_run_str = last_run.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        next_run_str = next_run.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                "UPDATE loops SET last_run = ?, next_run = ? WHERE id = ?",
                (last_run_str, next_run_str, loop_id),
            )


def _row_to_loop(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a loops table row tuple to a dict.

    Args:
        row: A tuple from a SELECT on the loops table.

    Returns:
        Dict with loop field names as keys.
    """
    return {
        "id": row[0],
        "name": row[1],
        "frequency": row[2],
        "prompt": row[3],
        "output_channel": row[4],
        "target": row[5],
        "model": row[6],
        "timezone": row[7],
        "enabled": bool(row[8]),
        "created_at": row[9],
        "last_run": row[10],
        "next_run": row[11],
    }
