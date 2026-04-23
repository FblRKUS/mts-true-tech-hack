from __future__ import annotations

from typing import Any


def get_agent_graph(*args: Any, **kwargs: Any):
    # Lazy import avoids heavy LangGraph initialization side effects
    # for lightweight modules that only need agent helper utilities.
    from .graph import get_agent_graph as _get_agent_graph

    return _get_agent_graph(*args, **kwargs)


__all__ = ["get_agent_graph"]
