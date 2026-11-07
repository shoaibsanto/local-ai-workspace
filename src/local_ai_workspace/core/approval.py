"""Tool execution approval policy engine.

Before the agent loop in core/chat.py executes an MCP tool call, it checks
this policy to decide whether to just run the tool, skip it, or pause and
ask the user. The policy is intentionally simple: a global default mode
plus per-tool overrides keyed by the *qualified* tool name
(`servername__toolname`, matching MCPManager's qualified-name format).

Risk classification (`classify_tool_risk`) is a cheap keyword heuristic, not
a guarantee. It exists to pick a sensible default (ask before anything that
looks consequential) -- it is not a security boundary, can be wrong in
either direction (false negatives: a destructive tool with an innocuous
name; false positives: a read-only tool that happens to mention "update" in
its docstring), and the policy model exists specifically so a user can
override any tool's classification explicitly via per_tool_overrides.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["readonly", "consequential"]
ToolDecision = Literal["allow", "deny", "ask"]
DefaultMode = Literal["auto_approve_readonly", "always_ask", "auto_approve_all"]

# Heuristic action-verb list. Matched as whole words (case-insensitive)
# against both the tool name and its description so e.g. "updates the
# cache" and "update_record" both flag, but "undated" does not.
_CONSEQUENTIAL_VERBS = (
    "delete",
    "remove",
    "send",
    "publish",
    "purchase",
    "buy",
    "write",
    "modify",
    "update",
    "execute",
    "drop",
)
_VERB_PATTERN = re.compile(
    r"\b(" + "|".join(_CONSEQUENTIAL_VERBS) + r")(e?s|e?d|ing)?\b", re.IGNORECASE
)


def classify_tool_risk(tool_name: str, description: str = "") -> RiskLevel:
    """Heuristic only -- see module docstring. Flags a tool as
    'consequential' if its name or description contains a recognizable
    action verb associated with state-changing operations (delete, remove,
    send, publish, purchase, buy, write, modify, update, execute, drop).
    Everything else defaults to 'readonly'. Callers that need certainty
    must rely on ApprovalPolicy.per_tool_overrides, not this function
    alone."""
    haystack = f"{tool_name} {description or ''}"
    # Tool names are often snake_case/camelCase; normalize separators to
    # spaces so word-boundary matching catches e.g. "delete_file".
    normalized = re.sub(r"[_\-.]+", " ", haystack)
    if _VERB_PATTERN.search(normalized):
        return "consequential"
    return "readonly"


class ApprovalPolicy(BaseModel):
    """Global (or per-server-override) tool execution approval policy."""

    default_mode: DefaultMode = "auto_approve_readonly"
    # Keyed by qualified tool name ("servername__toolname"), not just the
    # bare tool name -- the same tool name on two different servers can
    # have different risk profiles / trust levels.
    per_tool_overrides: dict[str, ToolDecision] = Field(default_factory=dict)

    def decide(self, qualified_tool_name: str, risk: RiskLevel) -> ToolDecision:
        """Resolve the final decision for a specific tool call. Per-tool
        overrides always win over the default mode."""
        override = self.per_tool_overrides.get(qualified_tool_name)
        if override is not None:
            return override

        if self.default_mode == "auto_approve_all":
            return "allow"
        if self.default_mode == "always_ask":
            return "ask"
        # auto_approve_readonly
        return "allow" if risk == "readonly" else "ask"


# Fixed boundary marker prefixed onto MCP tool results before they're fed
# back to the model. Tool output is attacker-influenceable content (the
# remote MCP server, or any data it returns, is not a trusted instruction
# source) -- this marker is a prompt-injection *mitigation*, signaling to
# the model (via its system prompt / training, not enforced mechanically)
# that what follows is data, not instructions from the user or operator.
# This is NOT a guarantee: a sufficiently adversarial tool result can still
# attempt to manipulate a model that doesn't respect the convention. Treat
# it as defense-in-depth, not a security boundary.
UNTRUSTED_TOOL_OUTPUT_MARKER = "[MCP TOOL OUTPUT - UNTRUSTED CONTENT FOLLOWS]"


def wrap_untrusted_tool_output(content: str) -> str:
    """Prefix `content` with the untrusted-content boundary marker."""
    return f"{UNTRUSTED_TOOL_OUTPUT_MARKER}\n{content}"


# ---------------------------------------------------------------------------
# Pending-approval persistence: when the agent loop in core/chat.py pauses on
# an "ask" decision, it writes this state to a per-conversation file so a
# page refresh / server restart doesn't lose track of what's awaiting the
# user's decision. Resolved via the resume API endpoint.
# ---------------------------------------------------------------------------


class PendingToolCall(BaseModel):
    tool_call: dict
    server_name: str | None = None
    risk: RiskLevel = "consequential"


class PendingApprovalState(BaseModel):
    conversation_id: str
    assistant_text: str = ""
    # Tool calls not yet resolved (including the one currently being asked
    # about, at index 0), in the order the model requested them.
    queue: list[PendingToolCall] = Field(default_factory=list)
    # Results already produced earlier in this same batch (allowed/denied
    # calls that didn't need to pause), to be combined with the rest once
    # the queue drains.
    results_so_far: list[dict] = Field(default_factory=list)
    iterations_remaining: int = 0


def _pending_approvals_path(conversation_id: str):
    from local_ai_workspace.storage.paths import conversation_dir

    return conversation_dir(conversation_id) / "pending_approvals.json"


def save_pending_approvals(state: PendingApprovalState) -> None:
    path = _pending_approvals_path(state.conversation_id)
    path.write_text(json.dumps(state.model_dump(), indent=2), encoding="utf-8")


def load_pending_approvals(conversation_id: str) -> PendingApprovalState | None:
    path = _pending_approvals_path(conversation_id)
    if not path.exists():
        return None
    try:
        return PendingApprovalState(**json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def clear_pending_approvals(conversation_id: str) -> None:
    path = _pending_approvals_path(conversation_id)
    if path.exists():
        path.unlink()
