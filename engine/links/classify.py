"""Sort a link into one kind, which decides whether and how it is checked."""
from urllib.parse import urldefrag, urlparse

CHECKABLE = {"internal", "external", "resource"}


def classify_link(raw_href: str, abs_url: str, cfg: dict) -> str:
    raw = (raw_href or "").strip()
    low = raw.lower()
    if not raw or raw == "#" or low.startswith("javascript:"):
        return "empty"
    if raw.startswith("#"):
        return "anchor"
    if low.startswith("mailto:"):
        return "mailto"
    if low.startswith("tel:"):
        return "tel"
    parsed = urlparse(abs_url)
    if parsed.scheme not in ("http", "https"):
        return "other"
    lc = cfg["link_check"]
    ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path.rsplit("/", 1)[-1] else ""
    if ext in lc["resource_extensions"]:
        return "resource"
    authored = urlparse(raw)
    is_relative = not authored.scheme and not authored.netloc   # "//host/x" is not relative
    if is_relative or (parsed.hostname or "") in lc["internal_hosts"]:
        return "internal"
    return "external"


def check_key(abs_url: str) -> str:
    """The URL actually requested: fragments never reach the server."""
    return urldefrag(abs_url).url
