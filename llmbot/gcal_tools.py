"""Google Calendar tools (wife's account) via CalDAV with OAuth 2.0.

Reads the CalDAV endpoint from GCAL_URL and authenticates using Google OAuth 2.0
credentials configured via GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and
GOOGLE_REFRESH_TOKEN.  Run ``llmbot gcal-auth`` once to obtain those credentials.
"""

import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import caldav  # type: ignore[import-untyped]
import icalendar  # type: ignore[import-untyped]

from .caldav_tools import (
    _find_calendar,
    _format_dt,
    _make_event_ical,
    _parse_dt,
    _parse_end_dt,
)
from .google_auth import get_caldav_client

logger = logging.getLogger(__name__)


def _get_gcal_connection() -> caldav.Principal:
    """Return an authenticated CalDAV principal for the Google Calendar account.

    Returns:
        Authenticated CalDAV principal.

    Raises:
        ValueError: If GCAL_URL is missing or OAuth credentials are not configured.
    """
    url = os.environ.get("GCAL_URL", "")
    if not url:
        msg = "Missing GCAL_URL environment variable"
        raise ValueError(msg)
    client = get_caldav_client(url)
    if client is None:
        msg = (
            "Google OAuth credentials not configured. "
            "Run 'llmbot gcal-auth' to set up authentication."
        )
        raise ValueError(msg)
    return client.principal()  # type: ignore[no-any-return]


def get_gcal_context() -> str | None:
    """Fetch available calendars and return a system-prompt context string.

    Returns:
        A formatted string naming available calendars, or None if not
        configured or unreachable.
    """
    try:
        principal = _get_gcal_connection()
        calendars = principal.calendars()
        if not calendars:
            return None
        names = ", ".join(f"'{c.name}'" for c in calendars)
    except Exception:  # noqa: BLE001
        return None
    else:
        local_tz = datetime.now().astimezone().strftime("%Z (UTC%z)")
        return (
            f"Google Calendar has the following calendars: {names}. "
            f"Use the gcal_* tools to read or modify them. "
            f"The server's local timezone is {local_tz}."
            f"When searching by date, assume any events returned by google are current even if their end date has passed"
            f"Google will return results that have incorrect start dates (for instance, an event may start on a Monday but repeat on a Wednesday)"
            f"If the start date and repeats information don't line up, use the repeats information to determine when the event actually is"
            f"For instance, this event occurs on any wednesday between the provided date range:"
            f"Tool result: Events in 'maeroselastic@gmail.com' (2026-04-11 to 2026-04-18):"
            f"       Maerose Training with Zach | 2025-09-17 19:00:00-05:00 -> 2025-09-17 20:00:00-05:00 (repeats: FREQ=WEEKLY;BYDAY=WE)"
            f"Also note that listing calendars in this tool only returns gcal calendars, you should also check caldav calendars"
        )


def gcal_list_calendars() -> str:
    """List all available calendars on the wife's Google Calendar account.

    IMPORTANT: This only lists calendars in gcal. You should also check caldav_list_calendars if the user is asking for a general list of calendar events.

    Returns:
        Formatted string listing calendar names and URLs, or an error message.
    """
    try:
        principal = _get_gcal_connection()
        calendars = principal.calendars()
        if not calendars:
            return "No calendars found."
        lines = ["Available calendars (wife's Google Calendar):"]
        lines.extend(f"  - {c.name} ({c.url})" for c in calendars)
        return "\n".join(lines)
    except ValueError as e:
        return f"Google Calendar configuration error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error listing calendars: {e}"


def gcal_get_events(
    calendar_name: str,
    start_date: str,
    end_date: str,
    timezone: str = "",
) -> str:
    """Get events from the wife's Google Calendar within a date range.

    Args:
        calendar_name: Name of the calendar to search.
        start_date: ISO 8601 start date, e.g. '2025-01-01'.
        end_date: ISO 8601 end date, e.g. '2025-01-31'.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.

    Returns:
        Formatted string with event details, or an error message.
    """
    try:
        principal = _get_gcal_connection()
        cal = _find_calendar(principal, calendar_name)
        start = _parse_dt(start_date, timezone)
        end = _parse_end_dt(end_date, timezone)
        events: list[Any] = cal.search(start=start, end=end, event=True, expand=False)
        if not events:
            return (
                f"No events found in '{calendar_name}'"
                f" between {start_date} and {end_date}."
            )
        lines = [f"Events in '{calendar_name}' ({start_date} to {end_date}):"]
        for event in events:
            comp = event.icalendar_component
            uid = str(comp.get("UID", "unknown"))
            summary = str(comp.get("SUMMARY", "(no title)"))
            dtstart = comp.get("DTSTART")
            dtend = comp.get("DTEND")
            location = str(comp.get("LOCATION", ""))
            description = str(comp.get("DESCRIPTION", ""))
            rrule = comp.get("RRULE")
            start_str = _format_dt(dtstart.dt, timezone) if dtstart else "?"
            end_str = _format_dt(dtend.dt, timezone) if dtend else "?"
            line = f"  [{uid}] {summary} | {start_str} -> {end_str}"
            if rrule:
                line += f" (repeats: {rrule.to_ical().decode()})"
            if location:
                line += f" @ {location}"
            if description:
                _max = 1000
                truncated = (
                    description[:_max] + " [truncated]"
                    if len(description) > _max
                    else description
                )
                line += f" | {truncated}"
            lines.append(line)
        return "\n".join(lines)
    except ValueError as e:
        return f"Google Calendar error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error getting events: {e}"


def gcal_create_event(  # noqa: PLR0913
    calendar_name: str,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    timezone: str = "",
    recurrence: str = "",
) -> str:
    """Create a new event on the wife's Google Calendar.

    Args:
        calendar_name: Name of the calendar to create the event in.
        summary: Event title.
        start: ISO 8601 start datetime, e.g. '2025-01-01T09:00:00'.
        end: ISO 8601 end datetime, e.g. '2025-01-01T10:00:00'.
        description: Optional event description.
        location: Optional event location.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.
        recurrence: Optional iCalendar RRULE string for repeating events.

    Returns:
        Confirmation message with the new event's UID, or an error message.
    """
    try:
        principal = _get_gcal_connection()
        cal = _find_calendar(principal, calendar_name)
        uid = str(uuid.uuid4())
        ical_str = _make_event_ical(
            uid=uid,
            summary=summary,
            dtstart=_parse_dt(start, timezone),
            dtend=_parse_dt(end, timezone),
            description=description,
            location=location,
            rrule=recurrence,
        )
        cal.save_event(ical=ical_str)
        logger.info(
            "Created gcal event '%s' (uid=%s) in calendar '%s'",
            summary,
            uid,
            calendar_name,
        )
    except ValueError as e:
        return f"Google Calendar error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error creating event: {e}"
    else:
        return f"Event created successfully. UID: {uid}"


def gcal_update_event(  # noqa: C901, PLR0913
    calendar_name: str,
    event_uid: str,
    summary: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    timezone: str = "",
    recurrence: str = "",
) -> str:
    """Update an existing event on the wife's Google Calendar by UID.

    Only fields with non-empty values are modified; omitted fields are unchanged.

    Args:
        calendar_name: Name of the calendar containing the event.
        event_uid: UID of the event to update.
        summary: New event title (optional).
        start: New start datetime in ISO 8601 format (optional).
        end: New end datetime in ISO 8601 format (optional).
        description: New event description (optional).
        location: New event location (optional).
        timezone: IANA timezone name (optional).
        recurrence: New iCalendar RRULE string (optional). Pass 'NONE' to
            remove recurrence.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        principal = _get_gcal_connection()
        cal = _find_calendar(principal, calendar_name)
        event = cal.event_by_uid(event_uid)
        ical_obj = icalendar.Calendar.from_ical(event.data)
        for component in ical_obj.walk():
            if component.name == "VEVENT":
                if summary:
                    component.pop("SUMMARY", None)
                    component.add("summary", summary)
                if start:
                    component.pop("DTSTART", None)
                    component.add("dtstart", _parse_dt(start, timezone))
                if end:
                    component.pop("DTEND", None)
                    component.add("dtend", _parse_dt(end, timezone))
                if description:
                    component.pop("DESCRIPTION", None)
                    component.add("description", description)
                if location:
                    component.pop("LOCATION", None)
                    component.add("location", location)
                if recurrence == "NONE":
                    component.pop("RRULE", None)
                elif recurrence:
                    component.pop("RRULE", None)
                    component.add("rrule", icalendar.vRecur.from_ical(recurrence))
                break
        event.data = ical_obj.to_ical().decode("utf-8")
        event.save()
        logger.info(
            "Updated gcal event uid=%s in calendar '%s'", event_uid, calendar_name
        )
    except ValueError as e:
        return f"Google Calendar error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error updating event: {e}"
    else:
        return f"Event '{event_uid}' updated successfully."


def gcal_delete_event(calendar_name: str, event_uid: str) -> str:
    """Delete an event from the wife's Google Calendar by UID.

    Args:
        calendar_name: Name of the calendar containing the event.
        event_uid: UID of the event to delete.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        principal = _get_gcal_connection()
        cal = _find_calendar(principal, calendar_name)
        event = cal.event_by_uid(event_uid)
        event.delete()
        logger.info(
            "Deleted gcal event uid=%s from calendar '%s'", event_uid, calendar_name
        )
    except ValueError as e:
        return f"Google Calendar error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error deleting event: {e}"
    else:
        return f"Event '{event_uid}' deleted successfully."


GCAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "gcal_list_calendars",
            "description": "List all available calendars on the wife's Google Calendar account",
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
            "name": "gcal_get_events",
            "description": "Get events from the wife's Google Calendar within a date range",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to search",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "ISO 8601 start date, e.g. '2025-01-01' or '2025-01-01T09:00:00'",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "ISO 8601 end date, e.g. '2025-01-31' or '2025-01-31T23:59:59'",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'America/Chicago'. Applied to both input and output. Defaults to system local time.",
                    },
                },
                "required": ["calendar_name", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_create_event",
            "description": "Create a new event on the wife's Google Calendar",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to create the event in",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "start": {
                        "type": "string",
                        "description": "ISO 8601 start datetime, e.g. '2025-01-01T09:00:00'",
                    },
                    "end": {
                        "type": "string",
                        "description": "ISO 8601 end datetime, e.g. '2025-01-01T10:00:00'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional event location",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'America/Chicago'. Applied to both input and output. Defaults to system local time.",
                    },
                    "recurrence": {
                        "type": "string",
                        "description": "iCalendar RRULE for repeating events, e.g. 'FREQ=WEEKLY;BYDAY=MO,WE,FR'",
                    },
                },
                "required": ["calendar_name", "summary", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_update_event",
            "description": "Update an event on the wife's Google Calendar by UID. Only given fields change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar containing the event",
                    },
                    "event_uid": {
                        "type": "string",
                        "description": "UID of the event to update",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New event title (leave empty to keep unchanged)",
                    },
                    "start": {
                        "type": "string",
                        "description": "New ISO 8601 start (empty = unchanged)",
                    },
                    "end": {
                        "type": "string",
                        "description": "New ISO 8601 end (empty = unchanged)",
                    },
                    "description": {
                        "type": "string",
                        "description": "New event description (empty = unchanged)",
                    },
                    "location": {
                        "type": "string",
                        "description": "New event location (empty = unchanged)",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'America/Chicago'. Applied to both input and output. Defaults to system local time.",
                    },
                    "recurrence": {
                        "type": "string",
                        "description": "New RRULE string (empty = unchanged). Pass 'NONE' to remove recurrence.",
                    },
                },
                "required": ["calendar_name", "event_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcal_delete_event",
            "description": "Delete an event from the wife's Google Calendar by UID",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar containing the event",
                    },
                    "event_uid": {
                        "type": "string",
                        "description": "UID of the event to delete",
                    },
                },
                "required": ["calendar_name", "event_uid"],
            },
        },
    },
]

GCAL_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "gcal_list_calendars": gcal_list_calendars,
    "gcal_get_events": gcal_get_events,
    "gcal_create_event": gcal_create_event,
    "gcal_update_event": gcal_update_event,
    "gcal_delete_event": gcal_delete_event,
}
