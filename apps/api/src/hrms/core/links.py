"""Links embedded in token emails (API audit H-3).

Every account email carries a one-time token. The https link on `web_app_base_url` always works in
a browser. When `mobile_app_link_base` is configured, a second link into the mobile app is added
next to it; the token is the same path segment in both, so nothing new is stored or logged.
"""

from hrms.core.config.settings import Settings


def mobile_link(settings: Settings, path: str, token: str) -> str | None:
    """`<mobile_app_link_base>/<path>/<token>`, or None when the mobile link is not configured."""
    if not settings.mobile_app_link_base:
        return None
    return f"{settings.mobile_app_link_base}/{path}/{token}"


def mobile_text(mobile_url: str | None) -> str:
    """Plain-text addendum placed after the web link; empty when there is no mobile link."""
    if not mobile_url:
        return ""
    return f"\n\nOn a phone with the HRMS app installed, open it with this link:\n{mobile_url}"


def mobile_html(mobile_url: str | None) -> str:
    if not mobile_url:
        return ""
    return (
        "<p>On a phone with the HRMS app installed, "
        f'<a href="{mobile_url}">open it in the app</a>.</p>'
    )
