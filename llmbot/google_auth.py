"""Central Google OAuth 2.0 authentication for all Google service integrations.

Reads credentials from GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and
GOOGLE_REFRESH_TOKEN environment variables.  All Google services (Calendar,
Gmail, etc.) share these credentials — run ``llmbot gcal-auth`` once to
obtain a refresh token scoped for all supported services.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import caldav  # type: ignore[import-untyped]
import google.oauth2.credentials  # type: ignore[import-untyped]
import urllib3

logger = logging.getLogger(__name__)

GOOGLE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/calendar",
    "https://mail.google.com/",
]

_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105


def _refresh_credentials(credentials: google.oauth2.credentials.Credentials) -> None:
    """Refresh an expired or missing Google OAuth access token via urllib3.

    Avoids ``google.auth.transport.requests`` to prevent a namespace conflict
    with the ``requests`` package in the Nix build sandbox.

    Args:
        credentials: The credentials object to refresh in-place.
    """
    http = urllib3.PoolManager()
    response = http.request(
        "POST",
        _TOKEN_URI,
        fields={
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    data: dict[str, Any] = json.loads(response.data.decode("utf-8"))
    if "error" in data:
        msg = f"Token refresh failed: {data.get('error_description', data['error'])}"
        raise ValueError(msg)
    credentials.token = data["access_token"]
    if "expires_in" in data:
        # google-auth compares expiry against datetime.utcnow() (naive), so
        # store the expiry as a naive UTC datetime to avoid TypeError.
        credentials.expiry = (
            datetime.now(UTC) + timedelta(seconds=int(data["expires_in"]))
        ).replace(tzinfo=None)


class _GoogleOAuth2Auth:
    """Callable auth handler that injects a Google OAuth 2.0 Bearer token.

    Compatible with the ``auth`` parameter of ``caldav.DAVClient`` and any
    ``requests.Session.request`` call, which accepts any callable of the form
    ``(PreparedRequest) -> PreparedRequest``.

    Automatically refreshes the token when it is expired or absent.
    """

    def __init__(self, credentials: google.oauth2.credentials.Credentials) -> None:
        """Initialise with a Google OAuth 2.0 credentials object.

        Args:
            credentials: A ``google.oauth2.credentials.Credentials`` instance
                constructed from a refresh token.  The access token field may
                be ``None``; it will be fetched on the first request.
        """
        self._credentials = credentials

    def __call__(self, r: Any) -> Any:  # noqa: ANN401
        """Attach the Bearer token to an outgoing request.

        Refreshes the token first if it is expired or not yet obtained.

        Args:
            r: A ``requests.PreparedRequest``; typed as ``Any`` to avoid
                importing the ``requests`` package at module level.

        Returns:
            The same request with an ``Authorization`` header added.
        """
        if not self._credentials.valid:
            _refresh_credentials(self._credentials)
        r.headers["Authorization"] = f"Bearer {self._credentials.token}"
        return r


def get_google_credentials() -> google.oauth2.credentials.Credentials | None:
    """Build Google OAuth 2.0 credentials from environment variables.

    Reads ``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET``, and
    ``GOOGLE_REFRESH_TOKEN``.

    Returns:
        A ``Credentials`` object ready for use, or ``None`` if any required
        environment variable is missing.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

    missing = [
        name
        for name, val in [
            ("GOOGLE_CLIENT_ID", client_id),
            ("GOOGLE_CLIENT_SECRET", client_secret),
            ("GOOGLE_REFRESH_TOKEN", refresh_token),
        ]
        if not val
    ]
    if missing:
        logger.debug("Google OAuth not configured; missing: %s", ", ".join(missing))
        return None

    return google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GOOGLE_SCOPES,
    )


def get_authorized_session() -> dict[str, str] | None:
    """Return auth headers for Google REST APIs (e.g. Gmail).

    Returns a dict with a fresh Bearer token suitable for passing to
    ``requests.Session.headers.update()``.  Callers should call this
    function again when requests return 401.

    Returns:
        A dict with an ``Authorization`` header, or ``None`` if OAuth
        credentials are not configured.
    """
    credentials = get_google_credentials()
    if credentials is None:
        return None
    _refresh_credentials(credentials)
    return {"Authorization": f"Bearer {credentials.token}"}


def get_caldav_client(url: str) -> caldav.DAVClient | None:
    """Return a CalDAV client authenticated via Google OAuth 2.0.

    Args:
        url: The CalDAV endpoint URL, e.g.
            ``https://apidata.googleusercontent.com/caldav/v2/user@gmail.com/user``.

    Returns:
        A ``caldav.DAVClient`` configured with OAuth auth, or ``None`` if
        credentials are not configured.
    """
    credentials = get_google_credentials()
    if credentials is None:
        return None
    return caldav.DAVClient(url=url, auth=_GoogleOAuth2Auth(credentials))
