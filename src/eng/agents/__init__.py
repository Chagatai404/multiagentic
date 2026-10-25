"""Role definitions, strict handoffs, and guarded execution."""

from eng.agents.registry import RoleDefinition, RoleRegistry, get_role, parse_handoff
from eng.agents.runtime import execute_role, workspace_digest

__all__ = [
    "RoleDefinition",
    "RoleRegistry",
    "execute_role",
    "get_role",
    "parse_handoff",
    "workspace_digest",
]
