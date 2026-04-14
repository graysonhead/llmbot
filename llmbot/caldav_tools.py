"""CalDAV tools for calendar event and task CRUD operations."""

import logging
import os
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import caldav  # type: ignore[import-untyped]
import icalendar  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def _get_connection(
    prefix: str = "CALDAV",
) -> tuple[caldav.DAVClient, caldav.Principal]:
    """Connect to a CalDAV server using environment variables.

    Args:
        prefix: Environment variable prefix, e.g. 'CALDAV' reads CALDAV_URL,
            CALDAV_USER, CALDAV_PASSWORD.  Use 'WIFE_CALDAV' for the second
            account.

    Returns:
        Tuple of (DAVClient, Principal) for the configured server.

    Raises:
        ValueError: If any required environment variables are missing.
    """
    url = os.environ.get(f"{prefix}_URL", "")
    username = os.environ.get(f"{prefix}_USER", "")
    password = os.environ.get(f"{prefix}_PASSWORD", "")
    missing = [
        name
        for name, val in [
            (f"{prefix}_URL", url),
            (f"{prefix}_USER", username),
            (f"{prefix}_PASSWORD", password),
        ]
        if not val
    ]
    if missing:
        msg = f"Missing CalDAV environment variables: {', '.join(missing)}"
        raise ValueError(msg)
    client = caldav.DAVClient(url=url, username=username, password=password, timeout=10)
    return client, client.principal()


def _find_calendar(principal: caldav.Principal, name: str) -> caldav.Calendar:
    """Find a calendar by name within a principal.

    Args:
        principal: The CalDAV principal to search within.
        name: The calendar name to find.

    Returns:
        The matching Calendar object.

    Raises:
        ValueError: If no calendar with the given name exists.
    """
    for cal in principal.calendars():
        if cal.name == name:
            return cal
    available = [c.name for c in principal.calendars()]
    msg = f"Calendar '{name}' not found. Available: {available}"
    raise ValueError(msg)


def _parse_end_dt(dt_str: str, tz: str = "") -> datetime:
    """Parse an end-of-range datetime, treating bare dates as end-of-day.

    When *dt_str* contains no time component (e.g. ``'2025-01-31'``), the time
    is set to ``23:59:59`` so that the range is inclusive of the whole day.
    Strings that already include a time component are passed through unchanged.

    Args:
        dt_str: ISO 8601 string, e.g. '2025-01-31' or '2025-01-31T23:59:59'.
        tz: IANA timezone name. Empty string means system local timezone.

    Returns:
        A UTC timezone-aware datetime representing the end of the range.
    """
    if "T" not in dt_str and " " not in dt_str:
        dt_str = f"{dt_str}T23:59:59"
    return _parse_dt(dt_str, tz)


def _parse_dt(dt_str: str, tz: str = "") -> datetime:
    """Parse an ISO 8601 datetime string into a UTC datetime.

    If the string already contains timezone info it is converted to UTC.
    Otherwise, the timezone is determined by ``tz`` if provided, falling back
    to the system local timezone, then converted to UTC.

    Storing all datetimes in UTC avoids VTIMEZONE serialization issues with
    servers that cannot resolve local timezone abbreviations during RRULE
    expansion.

    Args:
        dt_str: ISO 8601 string, e.g. '2025-01-01' or '2025-01-01T09:00:00'.
        tz: IANA timezone name, e.g. 'America/Chicago'. Empty string means
            use the system local timezone.

    Returns:
        A UTC timezone-aware datetime object.
    """
    utc = ZoneInfo("UTC")
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is not None:
        return dt.astimezone(utc)
    if tz:
        return dt.replace(tzinfo=ZoneInfo(tz)).astimezone(utc)
    return dt.astimezone(utc)


def _format_dt(dt: date | datetime, timezone: str = "") -> str:
    """Format a date or datetime value, converting to the given timezone.

    All-day events (bare ``date`` values) are returned as-is.  Timezone-aware
    datetimes are converted to *timezone* (or the system local timezone when
    *timezone* is empty).  Naive datetimes are assumed to be UTC before
    conversion.

    Args:
        dt: A ``date`` or ``datetime`` value from an iCal component.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Empty string
            means use the system local timezone.

    Returns:
        A formatted string representing the date/time.
    """
    if not isinstance(dt, datetime):
        return str(dt)
    target = ZoneInfo(timezone) if timezone else datetime.now().astimezone().tzinfo
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return str(dt.astimezone(target))


def _make_event_ical(  # noqa: PLR0913
    uid: str,
    summary: str,
    dtstart: datetime,
    dtend: datetime,
    description: str,
    location: str,
    rrule: str = "",
) -> str:
    """Build an iCal string for a VEVENT.

    Args:
        uid: Unique identifier for the event.
        summary: Event title.
        dtstart: Event start datetime.
        dtend: Event end datetime.
        description: Optional event description.
        location: Optional event location.
        rrule: Optional iCalendar RRULE string, e.g. 'FREQ=WEEKLY;BYDAY=MO,WE'.

    Returns:
        Serialized iCal string.
    """
    cal = icalendar.Calendar()
    cal.add("prodid", "-//llmbot//llmbot//EN")
    cal.add("version", "2.0")
    event = icalendar.Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", dtstart)
    event.add("dtend", dtend)
    if description:
        event.add("description", description)
    if location:
        event.add("location", location)
    if rrule:
        event.add("rrule", icalendar.vRecur.from_ical(rrule))
    cal.add_component(event)
    return str(cal.to_ical().decode("utf-8"))


def _make_todo_ical(
    uid: str,
    summary: str,
    due: datetime | None,
    description: str,
    priority: int,
) -> str:
    """Build an iCal string for a VTODO.

    Args:
        uid: Unique identifier for the task.
        summary: Task title.
        due: Optional due datetime.
        description: Optional task description.
        priority: Optional priority (1=highest, 9=lowest, 0=undefined).

    Returns:
        Serialized iCal string.
    """
    cal = icalendar.Calendar()
    cal.add("prodid", "-//llmbot//llmbot//EN")
    cal.add("version", "2.0")
    todo = icalendar.Todo()
    todo.add("uid", uid)
    todo.add("summary", summary)
    if due is not None:
        todo.add("due", due)
    if description:
        todo.add("description", description)
    if priority:
        todo.add("priority", priority)
    cal.add_component(todo)
    return str(cal.to_ical().decode("utf-8"))


def get_caldav_context() -> str | None:
    """Fetch available calendars and return a system-prompt context string.

    Returns:
        A formatted string naming available calendars, or None if CalDAV is
        not configured or unreachable.
    """
    try:
        _, principal = _get_connection()
        calendars = principal.calendars()
        if not calendars:
            return None
        names = ", ".join(f"'{c.name}'" for c in calendars)
    except Exception:  # noqa: BLE001
        return None
    else:
        local_tz = datetime.now().astimezone().strftime("%Z (UTC%z)")
        return (
            f"The user has the following CalDAV calendars available: {names}. "
            f"The server's local timezone is {local_tz}. When calling calendar "
            f"tools, omit the 'timezone' argument to use this default, or pass "
            f"an IANA timezone name (e.g. 'America/Chicago') to override it."
            f"Listing events from this tool only shows calendars in caldav, you should also check gcal"
        )


def caldav_list_calendars() -> str:
    """List all available calendars on the CalDAV server.

    Returns:
        Formatted string listing calendar names and URLs, or an error message.
    """
    try:
        _, principal = _get_connection()
        calendars = principal.calendars()
        if not calendars:
            return "No calendars found."
        lines = ["Available calendars:"]
        lines.extend(f"  - {c.name} ({c.url})" for c in calendars)
        return "\n".join(lines)
    except ValueError as e:
        return f"CalDAV configuration error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error listing calendars: {e}"


def caldav_get_events(
    calendar_name: str,
    start_date: str,
    end_date: str,
    timezone: str = "",
) -> str:
    """Get calendar events within a date range.

    Args:
        calendar_name: Name of the calendar to search.
        start_date: ISO 8601 start date, e.g. '2025-01-01'.
        end_date: ISO 8601 end date, e.g. '2025-01-31'.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.

    Returns:
        Formatted string with event details (UID, summary, times, location),
        or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        start = _parse_dt(start_date, timezone)
        end = _parse_end_dt(end_date, timezone)
        # Use expand=False to avoid server-side expansion of recurring events,
        # which fails when events contain non-IANA timezone abbreviations (e.g.
        # 'CDT') that the server's zoneinfo cannot resolve.
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
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error getting events: {e}"


def caldav_create_event(  # noqa: PLR0913
    calendar_name: str,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    timezone: str = "",
    recurrence: str = "",
) -> str:
    """Create a new calendar event.

    Args:
        calendar_name: Name of the calendar to create the event in.
        summary: Event title.
        start: ISO 8601 start datetime, e.g. '2025-01-01T09:00:00'.
        end: ISO 8601 end datetime, e.g. '2025-01-01T10:00:00'.
        description: Optional event description.
        location: Optional event location.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.
        recurrence: Optional iCalendar RRULE string for repeating events,
            e.g. 'FREQ=WEEKLY;BYDAY=MO,WE,FR' or 'FREQ=MONTHLY;COUNT=12'.

    Returns:
        Confirmation message with the new event's UID, or an error message.
    """
    try:
        _, principal = _get_connection()
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
            "Created event '%s' (uid=%s) in calendar '%s'", summary, uid, calendar_name
        )
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error creating event: {e}"
    else:
        return f"Event created successfully. UID: {uid}"


def caldav_update_event(  # noqa: C901, PLR0913
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
    """Update an existing calendar event by UID.

    Only fields with non-empty values are modified; omitted fields are unchanged.

    Args:
        calendar_name: Name of the calendar containing the event.
        event_uid: UID of the event to update.
        summary: New event title (optional).
        start: New start datetime in ISO 8601 format (optional).
        end: New end datetime in ISO 8601 format (optional).
        description: New event description (optional).
        location: New event location (optional).
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.
        recurrence: New iCalendar RRULE string (optional). Pass 'NONE' to
            remove recurrence from the event.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        _, principal = _get_connection()
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
        logger.info("Updated event uid=%s in calendar '%s'", event_uid, calendar_name)
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error updating event: {e}"
    else:
        return f"Event '{event_uid}' updated successfully."


def caldav_delete_event(calendar_name: str, event_uid: str) -> str:
    """Delete a calendar event by UID.

    Args:
        calendar_name: Name of the calendar containing the event.
        event_uid: UID of the event to delete.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        event = cal.event_by_uid(event_uid)
        event.delete()
        logger.info("Deleted event uid=%s from calendar '%s'", event_uid, calendar_name)
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error deleting event: {e}"
    else:
        return f"Event '{event_uid}' deleted successfully."


def caldav_get_tasks(calendar_name: str) -> str:
    """Get all tasks (VTODOs) from a calendar.

    Args:
        calendar_name: Name of the calendar to retrieve tasks from.

    Returns:
        Formatted string with task details (UID, summary, due date, status,
        priority), or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        todos = cal.todos()
        if not todos:
            return f"No tasks found in '{calendar_name}'."
        lines = [f"Tasks in '{calendar_name}':"]
        for todo in todos:
            comp = todo.icalendar_component
            uid = str(comp.get("UID", "unknown"))
            summary = str(comp.get("SUMMARY", "(no title)"))
            due = comp.get("DUE")
            status = str(comp.get("STATUS", ""))
            priority = str(comp.get("PRIORITY", ""))
            description = str(comp.get("DESCRIPTION", ""))
            due_str = str(due.dt) if due else "no due date"
            line = f"  [{uid}] {summary} | due: {due_str}"
            if status:
                line += f" | status: {status}"
            if priority:
                line += f" | priority: {priority}"
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
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error getting tasks: {e}"


def caldav_create_task(  # noqa: PLR0913
    calendar_name: str,
    summary: str,
    due: str = "",
    description: str = "",
    priority: int = 0,
    timezone: str = "",
) -> str:
    """Create a new task (VTODO) in a calendar.

    Args:
        calendar_name: Name of the calendar to create the task in.
        summary: Task title.
        due: Optional due datetime in ISO 8601 format, e.g. '2025-01-15'.
        description: Optional task description.
        priority: Optional priority (1=highest, 9=lowest, 0=undefined).
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.

    Returns:
        Confirmation message with the new task's UID, or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        uid = str(uuid.uuid4())
        due_dt = _parse_dt(due, timezone) if due else None
        ical_str = _make_todo_ical(
            uid=uid,
            summary=summary,
            due=due_dt,
            description=description,
            priority=priority,
        )
        cal.save_todo(ical=ical_str)
        logger.info(
            "Created task '%s' (uid=%s) in calendar '%s'", summary, uid, calendar_name
        )
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error creating task: {e}"
    else:
        return f"Task created successfully. UID: {uid}"


def caldav_update_task(  # noqa: C901, PLR0913
    calendar_name: str,
    task_uid: str,
    summary: str = "",
    due: str = "",
    description: str = "",
    priority: int = 0,
    status: str = "",
    timezone: str = "",
) -> str:
    """Update an existing task (VTODO) by UID.

    Only fields with non-empty/non-zero values are modified; omitted fields are
    unchanged.

    Args:
        calendar_name: Name of the calendar containing the task.
        task_uid: UID of the task to update.
        summary: New task title (optional).
        due: New due datetime in ISO 8601 format (optional).
        description: New task description (optional).
        priority: New priority 1-9 (optional, 0 means no change).
        status: New status, e.g. 'NEEDS-ACTION', 'IN-PROCESS', 'COMPLETED'
            (optional).
        timezone: IANA timezone name, e.g. 'America/Chicago'. Defaults to
            the system local timezone if omitted.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        todo = cal.todo_by_uid(task_uid)
        ical_obj = icalendar.Calendar.from_ical(todo.data)
        for component in ical_obj.walk():
            if component.name == "VTODO":
                if summary:
                    component.pop("SUMMARY", None)
                    component.add("summary", summary)
                if due:
                    component.pop("DUE", None)
                    component.add("due", _parse_dt(due, timezone))
                if description:
                    component.pop("DESCRIPTION", None)
                    component.add("description", description)
                if priority:
                    component.pop("PRIORITY", None)
                    component.add("priority", priority)
                if status:
                    component.pop("STATUS", None)
                    component.add("status", status)
                break
        todo.data = ical_obj.to_ical().decode("utf-8")
        todo.save()
        logger.info("Updated task uid=%s in calendar '%s'", task_uid, calendar_name)
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error updating task: {e}"
    else:
        return f"Task '{task_uid}' updated successfully."


def caldav_delete_task(calendar_name: str, task_uid: str) -> str:
    """Delete a task (VTODO) by UID.

    Args:
        calendar_name: Name of the calendar containing the task.
        task_uid: UID of the task to delete.

    Returns:
        Confirmation message, or an error message.
    """
    try:
        _, principal = _get_connection()
        cal = _find_calendar(principal, calendar_name)
        todo = cal.todo_by_uid(task_uid)
        todo.delete()
        logger.info("Deleted task uid=%s from calendar '%s'", task_uid, calendar_name)
    except ValueError as e:
        return f"CalDAV error: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error deleting task: {e}"
    else:
        return f"Task '{task_uid}' deleted successfully."


CALDAV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "caldav_list_calendars",
            "description": "List all available calendars on the CalDAV server",
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
            "name": "caldav_get_events",
            "description": "Get calendar events within a date range",
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
            "name": "caldav_create_event",
            "description": "Create a new calendar event",
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
                        "description": "iCalendar RRULE for repeating events, e.g. 'FREQ=WEEKLY;BYDAY=MO,WE,FR' or 'FREQ=MONTHLY;COUNT=12' or 'FREQ=DAILY;UNTIL=2025-12-31T000000Z'",
                    },
                },
                "required": ["calendar_name", "summary", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "caldav_update_event",
            "description": "Update a calendar event by UID. Only given fields change.",
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
            "name": "caldav_delete_event",
            "description": "Delete a calendar event by UID",
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
    {
        "type": "function",
        "function": {
            "name": "caldav_get_tasks",
            "description": "Get all tasks (todos) from a calendar",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to retrieve tasks from",
                    },
                },
                "required": ["calendar_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "caldav_create_task",
            "description": "Create a new task (todo) in a calendar",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to create the task in",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Task title",
                    },
                    "due": {
                        "type": "string",
                        "description": "Optional ISO 8601 due date, e.g. '2025-01-15'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional task description",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority: 1=highest, 9=lowest, 0=undefined",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'America/Chicago'. Applied to both input and output. Defaults to system local time.",
                    },
                },
                "required": ["calendar_name", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "caldav_update_task",
            "description": "Update a task (todo) by UID. Only given fields change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar containing the task",
                    },
                    "task_uid": {
                        "type": "string",
                        "description": "UID of the task to update",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New task title (leave empty to keep unchanged)",
                    },
                    "due": {
                        "type": "string",
                        "description": "New ISO 8601 due date (empty = unchanged)",
                    },
                    "description": {
                        "type": "string",
                        "description": "New task description (empty = unchanged)",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "New priority 1-9 (0 means no change)",
                    },
                    "status": {
                        "type": "string",
                        "description": "VTODO status: NEEDS-ACTION, IN-PROCESS, COMPLETED",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. 'America/Chicago'. Applied to both input and output. Defaults to system local time.",
                    },
                },
                "required": ["calendar_name", "task_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "caldav_delete_task",
            "description": "Delete a task (todo) by UID",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar containing the task",
                    },
                    "task_uid": {
                        "type": "string",
                        "description": "UID of the task to delete",
                    },
                },
                "required": ["calendar_name", "task_uid"],
            },
        },
    },
]

CALDAV_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "caldav_list_calendars": caldav_list_calendars,
    "caldav_get_events": caldav_get_events,
    "caldav_create_event": caldav_create_event,
    "caldav_update_event": caldav_update_event,
    "caldav_delete_event": caldav_delete_event,
    "caldav_get_tasks": caldav_get_tasks,
    "caldav_create_task": caldav_create_task,
    "caldav_update_task": caldav_update_task,
    "caldav_delete_task": caldav_delete_task,
}
