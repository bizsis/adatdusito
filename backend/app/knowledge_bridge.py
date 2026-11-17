"""Integration hook to Claude's KNOWLEDGE-01, never a replacement learning engine."""

from importlib.util import find_spec


def available():
    return find_spec("app.knowledge") is not None


def schedule_source(source_id):
    if not available():
        return False
    from app.knowledge import schedule

    schedule(source_id=source_id)
    return True
