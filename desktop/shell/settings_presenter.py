"""Presentation helpers shared by settings UI code."""


def truncate_status_text(text, limit=45):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."
