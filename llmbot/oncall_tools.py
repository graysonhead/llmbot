"""On-call calendar tools for Grayson's PagerDuty webcal feed."""

import logging
import os
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import icalendar  # type: ignore[import-untyped]
import requests  # type: ignore[import-untyped]

from .caldav_tools import _format_dt, _parse_dt, _parse_end_dt

logger = logging.getLogger(__name__)

_ONCALL_WEBCAL_URL = os.environ.get("ONCALL_WEBCAL_URL", "")


def _fetch_oncall_ical() -> bytes:
    """Fetch the raw iCal data from the PagerDuty webcal feed.

    Returns:
        Raw iCal bytes.

    Raises:
        requests.RequestException: If the HTTP request fails.
    """
    url = _ONCALL_WEBCAL_URL.replace("webcal://", "https://", 1)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return bytes(response.content)


def _to_aware_datetime(dt: date | datetime, utc: ZoneInfo) -> datetime:
    """Convert a date or datetime to a UTC-aware datetime."""
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=utc)


def is_oncall() -> str:  # noqa: C901
    """Check whether Grayson is currently on-call, going on-call today, or going off-call today.

    Also detects mid-day coverage gaps: if Grayson has on-call shifts both before
    and after the current time today, reports that he is on-call but has coverage
    during the gap.

    Returns:
        A plain-text status string.
    """
    try:
        raw = _fetch_oncall_ical()
        cal = icalendar.Calendar.from_ical(raw)
        utc = ZoneInfo("UTC")
        now = datetime.now().astimezone()
        today = now.date()

        # Collect all events that touch today
        today_events: list[tuple[datetime, datetime]] = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")
            if dtstart is None:
                continue
            ev_start = _to_aware_datetime(dtstart.dt, utc).astimezone()
            ev_end = _to_aware_datetime(
                dtend.dt if dtend else dtstart.dt, utc
            ).astimezone()
            if ev_start.date() <= today <= ev_end.date():
                today_events.append((ev_start, ev_end))

        today_events.sort()

        # Currently inside a shift
        for ev_start, ev_end in today_events:
            if ev_start <= now < ev_end:
                if ev_end.date() == today:
                    return "Grayson is going off-call today"
                return "Grayson is currently on-call"

        # Not currently in a shift — check for gap vs. simple start/end
        past = [(s, e) for s, e in today_events if e <= now]
        future = [(s, e) for s, e in today_events if s > now]

        if past and future:
            gap_start = past[-1][1].strftime("%-I:%M %p %Z")
            gap_end = future[0][0].strftime("%-I:%M %p %Z")
            return f"Grayson is on-call but has coverage from {gap_start} to {gap_end}"

        if future:
            return "Grayson is going on-call today"
    except Exception as e:  # noqa: BLE001
        return f"Error checking on-call status: {e}"
    else:
        return "Grayson isn't on-call"


def oncall_get_events(
    start_date: str,
    end_date: str,
    timezone: str = "",
) -> str:
    """Get events from Grayson's PagerDuty on-call calendar within a date range.

    Args:
        start_date: ISO 8601 start date, e.g. '2025-01-01'.
        end_date: ISO 8601 end date, e.g. '2025-01-31'.
        timezone: IANA timezone name, e.g. 'America/Chicago'. Used for both
            input parsing and output display. Defaults to system local timezone.

    Returns:
        Formatted string with on-call event details, or an error message.
    """
    try:
        raw = _fetch_oncall_ical()
        cal = icalendar.Calendar.from_ical(raw)
        utc = ZoneInfo("UTC")
        start = _parse_dt(start_date, timezone)
        end = _parse_end_dt(end_date, timezone)

        events = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")
            if dtstart is None:
                continue
            ev_start = _to_aware_datetime(dtstart.dt, utc)
            ev_end = _to_aware_datetime(dtend.dt if dtend else dtstart.dt, utc)

            # Include events that overlap the requested range
            if ev_end <= start or ev_start >= end:
                continue
            events.append((ev_start, ev_end, component))

        if not events:
            return f"No on-call events found between {start_date} and {end_date}."

        events.sort(key=lambda x: x[0])
        lines = [f"Grayson's on-call events ({start_date} to {end_date}):"]
        for ev_start, ev_end, comp in events:
            summary = str(comp.get("SUMMARY", "(no title)"))
            description = str(comp.get("DESCRIPTION", ""))
            start_str = _format_dt(ev_start, timezone)
            end_str = _format_dt(ev_end, timezone)
            line = f"  {summary} | {start_str} -> {end_str}"
            if description:
                _max = 500
                truncated = (
                    description[:_max] + " [truncated]"
                    if len(description) > _max
                    else description
                )
                line += f" | {truncated}"
            lines.append(line)
        return "\n".join(lines)
    except requests.RequestException as e:
        return f"Error fetching on-call calendar: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error parsing on-call calendar: {e}"


ONCALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "is_oncall",
            "description": (
                "Check whether Grayson is currently on-call, going on-call today, "
                "going off-call today, or not on-call at all."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "oncall_get_events",
            "description": (
                "Get events from Grayson's PagerDuty on-call calendar within a date range"
            ),
            "parameters": {
                "type": "object",
                "properties": {
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
                "required": ["start_date", "end_date"],
            },
        },
    },
]

ONCALL_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "is_oncall": is_oncall,
    "oncall_get_events": oncall_get_events,
}
