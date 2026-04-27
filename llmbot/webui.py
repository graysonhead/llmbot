# Copyright (C) 2024 Grayson Head <grayson@graysonhead.net>
# SPDX-License-Identifier: GPL-3.0-or-later
"""FastAPI web UI for managing llmbot memories, loops, and channel context."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, FastAPI, Form, Request  # type: ignore[import-not-found]
from fastapi.responses import (  # type: ignore[import-not-found]
    HTMLResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]
from fastapi.templating import Jinja2Templates  # type: ignore[import-not-found]

from .loop_tools import compute_next_run, is_valid_frequency
from .memory import parse_consolidation_response

if TYPE_CHECKING:
    from .backends import LLMBackend
    from .memory import MemoryStore

logger = logging.getLogger(__name__)

_CATEGORIES = ("fact", "preference", "task", "note", "workflow")


def _templates_dir() -> str:
    return str(files("llmbot").joinpath("templates"))


def _static_dir() -> str:
    return str(files("llmbot").joinpath("static"))


# ------------------------------------------------------------------
# Memories router
# ------------------------------------------------------------------


def _memory_router(
    memory_store: MemoryStore,
    templates: Jinja2Templates,
) -> APIRouter:
    """Build and return the /memories API router."""
    router = APIRouter(prefix="/memories")

    @router.get("", response_class=HTMLResponse)
    async def memories_list(request: Request) -> HTMLResponse:
        """List all memories grouped by user_id."""
        all_memories = memory_store.get_all_memories()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for mem in all_memories:
            grouped.setdefault(mem["user_id"], []).append(mem)
        return templates.TemplateResponse(
            "memories.html",
            {"request": request, "grouped": grouped, "categories": _CATEGORIES},
        )

    @router.get("/new", response_class=HTMLResponse)
    async def memory_new_form(request: Request, error: str = "") -> HTMLResponse:
        """Render the create-memory form."""
        return templates.TemplateResponse(
            "memory_form.html",
            {
                "request": request,
                "memory": None,
                "categories": _CATEGORIES,
                "error": error,
            },
        )

    @router.post("/new")
    async def memory_create(
        user_id: Annotated[str, Form()],
        content: Annotated[str, Form()],
        tags: Annotated[str, Form()] = "",
        category: Annotated[str, Form()] = "note",
    ) -> RedirectResponse:
        """Handle memory creation form submission."""
        try:
            uid = int(user_id.strip())
        except ValueError:
            return RedirectResponse(
                "/memories/new?error=User+ID+must+be+a+number", status_code=303
            )
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        memory_store.create_memory(uid, content.strip(), tag_list, category)
        return RedirectResponse("/memories", status_code=303)

    @router.get("/{memory_id}/edit", response_class=HTMLResponse)
    async def memory_edit_form(
        request: Request,
        memory_id: int,
        error: str = "",
    ) -> HTMLResponse:
        """Render the edit-memory form."""
        mem = memory_store.get_memory(memory_id)
        if mem is None:
            return HTMLResponse("Memory not found", status_code=404)
        return templates.TemplateResponse(
            "memory_form.html",
            {
                "request": request,
                "memory": mem,
                "categories": _CATEGORIES,
                "error": error,
            },
        )

    @router.post("/{memory_id}/edit")
    async def memory_update(
        memory_id: int,
        content: Annotated[str, Form()],
        tags: Annotated[str, Form()] = "",
        category: Annotated[str, Form()] = "note",
    ) -> RedirectResponse:
        """Handle memory edit form submission."""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        memory_store.update_memory(memory_id, content.strip(), tag_list, category)
        return RedirectResponse("/memories", status_code=303)

    @router.post("/{memory_id}/delete")
    async def memory_delete(memory_id: int) -> RedirectResponse:
        """Delete a memory and redirect to the memories list."""
        memory_store.delete_memory(memory_id)
        return RedirectResponse("/memories", status_code=303)

    return router


# ------------------------------------------------------------------
# Loops router
# ------------------------------------------------------------------


def _loop_router(  # noqa: C901
    memory_store: MemoryStore,
    templates: Jinja2Templates,
) -> APIRouter:
    """Build and return the /loops API router."""
    router = APIRouter(prefix="/loops")

    @router.get("", response_class=HTMLResponse)
    async def loops_list(request: Request, msg: str = "") -> HTMLResponse:
        """List all loops."""
        loops = memory_store.list_loops()
        return templates.TemplateResponse(
            "loops.html", {"request": request, "loops": loops, "msg": msg}
        )

    @router.get("/new", response_class=HTMLResponse)
    async def loop_new_form(request: Request, error: str = "") -> HTMLResponse:
        """Render the create-loop form."""
        return templates.TemplateResponse(
            "loop_form.html", {"request": request, "loop": None, "error": error}
        )

    @router.post("/new")
    async def loop_create(  # noqa: PLR0913
        name: Annotated[str, Form()],
        frequency: Annotated[str, Form()],
        prompt: Annotated[str, Form()],
        output_channel: Annotated[str, Form()],
        target: Annotated[str, Form()] = "",
        model: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        """Handle loop creation form submission."""
        freq = frequency.strip()
        if not is_valid_frequency(freq):
            return RedirectResponse(
                f"/loops/new?error=Invalid+frequency+format:+{freq}", status_code=303
            )
        try:
            channel_id = int(output_channel.strip())
        except ValueError:
            return RedirectResponse(
                "/loops/new?error=Output+channel+must+be+a+number", status_code=303
            )
        memory_store.create_loop(
            name=name.strip(),
            frequency=freq,
            prompt=prompt.strip(),
            output_channel=channel_id,
            next_run=compute_next_run(freq),
            target=target.strip(),
            model=model.strip(),
        )
        return RedirectResponse("/loops", status_code=303)

    @router.get("/{loop_id}/edit", response_class=HTMLResponse)
    async def loop_edit_form(
        request: Request, loop_id: int, error: str = ""
    ) -> HTMLResponse:
        """Render the edit-loop form."""
        loop = memory_store.get_loop(loop_id)
        if loop is None:
            return HTMLResponse("Loop not found", status_code=404)
        return templates.TemplateResponse(
            "loop_form.html", {"request": request, "loop": loop, "error": error}
        )

    @router.post("/{loop_id}/edit")
    async def loop_update(  # noqa: PLR0913
        loop_id: int,
        name: Annotated[str, Form()],
        frequency: Annotated[str, Form()],
        prompt: Annotated[str, Form()],
        output_channel: Annotated[str, Form()],
        target: Annotated[str, Form()] = "",
        model: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        """Handle loop edit form submission."""
        freq = frequency.strip()
        if not is_valid_frequency(freq):
            return RedirectResponse(
                f"/loops/{loop_id}/edit?error=Invalid+frequency+format:+{freq}",
                status_code=303,
            )
        try:
            channel_id = int(output_channel.strip())
        except ValueError:
            return RedirectResponse(
                f"/loops/{loop_id}/edit?error=Output+channel+must+be+a+number",
                status_code=303,
            )
        next_run_str = (
            compute_next_run(freq).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        )
        memory_store.update_loop(
            loop_id,
            name=name.strip(),
            frequency=freq,
            prompt=prompt.strip(),
            output_channel=channel_id,
            target=target.strip(),
            model=model.strip(),
            next_run=next_run_str,
        )
        return RedirectResponse("/loops", status_code=303)

    @router.post("/{loop_id}/delete")
    async def loop_delete(loop_id: int) -> RedirectResponse:
        """Delete a loop and redirect to the loops list."""
        memory_store.delete_loop(loop_id)
        return RedirectResponse("/loops", status_code=303)

    @router.post("/{loop_id}/enable")
    async def loop_enable(loop_id: int) -> RedirectResponse:
        """Enable a loop."""
        memory_store.update_loop(loop_id, enabled=1)
        return RedirectResponse("/loops", status_code=303)

    @router.post("/{loop_id}/disable")
    async def loop_disable(loop_id: int) -> RedirectResponse:
        """Disable a loop."""
        memory_store.update_loop(loop_id, enabled=0)
        return RedirectResponse("/loops", status_code=303)

    @router.post("/{loop_id}/run")
    async def loop_run_now(loop_id: int) -> RedirectResponse:
        """Queue a loop to run on the next scheduler tick by setting next_run to now."""
        loop = memory_store.get_loop(loop_id)
        if loop is None:
            return RedirectResponse("/loops?msg=Loop+not+found", status_code=303)
        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        memory_store.update_loop(loop_id, next_run=now_str)
        name = loop["name"]
        return RedirectResponse(
            f"/loops?msg=Loop+%22{name}%22+queued+for+next+scheduler+tick",
            status_code=303,
        )

    @router.post("/clear-scheduled")
    async def loops_clear_scheduled() -> RedirectResponse:
        """Reset all loops' next_run to their proper future schedule."""
        for loop in memory_store.list_loops():
            next_run = compute_next_run(loop["frequency"])
            memory_store.update_loop(
                loop["id"],
                next_run=next_run.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            )
        return RedirectResponse("/loops?msg=Scheduled+runs+cleared", status_code=303)

    return router


# ------------------------------------------------------------------
# Channels router
# ------------------------------------------------------------------


def _channel_router(  # noqa: C901
    memory_store: MemoryStore,
    templates: Jinja2Templates,
    backend: LLMBackend | None = None,
) -> APIRouter:
    """Build and return the /channels API router."""
    router = APIRouter(prefix="/channels")

    @router.get("", response_class=HTMLResponse)
    async def channels_list(request: Request) -> HTMLResponse:
        """List all channels with summary previews."""
        channels = memory_store.get_all_channel_summaries()
        return templates.TemplateResponse(
            "channels.html", {"request": request, "channels": channels}
        )

    @router.get("/{channel_id}", response_class=HTMLResponse)
    async def channel_detail(request: Request, channel_id: int) -> HTMLResponse:
        """Show full context for a channel: summary and recent messages."""
        summary = memory_store.get_summary(channel_id)
        history = memory_store.get_raw_history(channel_id)
        summary_history = memory_store.get_summary_history(channel_id, limit=5)
        if summary is None and not history:
            return HTMLResponse("Channel not found", status_code=404)
        return templates.TemplateResponse(
            "channel_detail.html",
            {
                "request": request,
                "channel_id": channel_id,
                "summary": summary or "",
                "history": history,
                "summary_history": summary_history,
                "can_consolidate": backend is not None,
            },
        )

    @router.post("/{channel_id}/consolidate", response_model=None)
    async def channel_consolidate(channel_id: int) -> RedirectResponse | HTMLResponse:
        """Run immediate memory consolidation for a channel."""
        if backend is None:
            return HTMLResponse("No LLM backend configured", status_code=503)
        existing_summary = memory_store.get_summary(channel_id) or ""
        history = memory_store.get_raw_history(channel_id)
        if not history and not existing_summary:
            return RedirectResponse(f"/channels/{channel_id}", status_code=303)
        history_text = "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)
        consolidation_prompt = (
            f"Current summary:\n{existing_summary or '(none)'}\n\n"
            f"Recent messages:\n{history_text}\n\n"
            "Review the above. Output a JSON object with exactly two keys:\n"
            '1. "summary": updated running summary — preserve important facts, '
            "decisions, ongoing tasks, and user preferences. Be concise.\n"
            '2. "memories": list of objects with keys user_id (int Discord snowflake), '
            "content (str), tags (list[str]), category "
            "(one of: fact, preference, task, note, workflow) — "
            "only include genuinely useful long-term facts.\n\n"
            "Output only the JSON object, no other text."
        )

        def _run() -> None:
            response = backend.api_chat(
                [{"role": "user", "content": consolidation_prompt}],
                "You are a memory consolidation assistant. Output only valid JSON.",
            )
            raw_text = backend.extract_text(response)
            parsed = parse_consolidation_response(raw_text)
            memory_store.save_summary(channel_id, existing_summary, parsed["summary"])
            valid_memories = [
                m
                for m in parsed.get("memories", [])
                if isinstance(m.get("user_id"), int) and m.get("content")
            ]
            if valid_memories:
                memory_store.save_memories(valid_memories)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)
        return RedirectResponse(f"/channels/{channel_id}", status_code=303)

    @router.post("/{channel_id}/clear-summary")
    async def channel_clear_summary(channel_id: int) -> RedirectResponse:
        """Clear the current summary for a channel."""
        memory_store.clear_summary(channel_id)
        return RedirectResponse(f"/channels/{channel_id}", status_code=303)

    @router.post("/{channel_id}/clear-history")
    async def channel_clear_history(channel_id: int) -> RedirectResponse:
        """Clear recent messages for a channel."""
        memory_store.clear_raw_history(channel_id)
        return RedirectResponse(f"/channels/{channel_id}", status_code=303)

    return router


# ------------------------------------------------------------------
# Tool call logs router
# ------------------------------------------------------------------


def _tool_call_log_router(
    memory_store: MemoryStore,
    templates: Jinja2Templates,
) -> APIRouter:
    """Build and return the /tool-calls API router."""
    router = APIRouter(prefix="/tool-calls")

    @router.get("/{log_id}", response_class=HTMLResponse)
    async def tool_call_detail(request: Request, log_id: int) -> HTMLResponse:
        """Show tool calls and results for a single interaction."""
        log = memory_store.get_tool_call_log(log_id)
        if log is None:
            return HTMLResponse("Tool call log not found", status_code=404)
        return templates.TemplateResponse(
            "tool_call_detail.html",
            {"request": request, "log": log},
        )

    return router


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------


def create_app(memory_store: MemoryStore, backend: LLMBackend | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        memory_store: Initialized MemoryStore instance to use for all DB access.

    Returns:
        Configured FastAPI app ready to serve.
    """
    app = FastAPI(title="llmbot admin")
    templates = Jinja2Templates(directory=_templates_dir())
    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Render the dashboard with summary counts."""
        memories = memory_store.get_all_memories()
        loops = memory_store.list_loops()
        channels = memory_store.get_all_channel_summaries()
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "memory_count": len(memories),
                "loop_count": len(loops),
                "channel_count": len(channels),
                "active_loop_count": sum(1 for lo in loops if lo["enabled"]),
            },
        )

    @app.get("/api/memories")
    async def api_memories() -> list[dict[str, Any]]:
        """Return all memories as JSON."""
        mems = memory_store.get_all_memories()
        for m in mems:
            m["tags"] = json.dumps(m["tags"])
        return mems

    @app.get("/api/loops")
    async def api_loops() -> list[dict[str, Any]]:
        """Return all loops as JSON."""
        return memory_store.list_loops()

    app.include_router(_memory_router(memory_store, templates))
    app.include_router(_loop_router(memory_store, templates))
    app.include_router(_channel_router(memory_store, templates, backend))
    app.include_router(_tool_call_log_router(memory_store, templates))

    return app
