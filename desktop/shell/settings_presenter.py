"""Presentation helpers shared by settings UI code."""


def truncate_status_text(text, limit=45):
    """Trim long status text for compact settings labels."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."
