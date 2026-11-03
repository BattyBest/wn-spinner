"""A small robots.txt parser.

The standard library's parser ignores ``*`` and ``$`` wildcards, which sites such
as Qidian use (``Disallow: /so/*``), so this follows the common longest-match rules
instead: the most specific agent group wins, then the longest matching path rule,
and Allow beats Disallow on a tie.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: float | None = None


def _pattern(path: str) -> re.Pattern[str]:
    end = path.endswith("$")
    body = path[:-1] if end else path
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if end else ""))


class RobotsRules:
    def __init__(self, groups: list[_Group], *, allow_all: bool = False, deny_all: bool = False):
        self._groups = groups
        self.allow_all = allow_all
        self.deny_all = deny_all

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[_Group] = []
        current: _Group | None = None
        collecting_agents = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if current is None or not collecting_agents:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
                collecting_agents = True
                continue
            collecting_agents = False
            if current is None:
                continue
            if key in ("allow", "disallow"):
                if value:  # an empty Disallow allows everything and adds no rule
                    current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    current.crawl_delay = float(value)
        return cls(groups)

    @classmethod
    def from_status(cls, status: int) -> RobotsRules:
        """Rules implied by a non-200 robots.txt response."""
        if status in (401, 403):
            return cls([], deny_all=True)
        if 400 <= status < 500:
            return cls([], allow_all=True)
        raise ValueError(f"robots.txt status {status} gives no rules")

    def _select(self, token: str) -> list[_Group]:
        token = token.lower()
        named = [g for g in self._groups if token in g.agents]
        return named or [g for g in self._groups if "*" in g.agents]

    def allowed(self, token: str, path: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all:
            return True
        best_len, best_allow = -1, True
        for group in self._select(token):
            for allow, pattern in group.rules:
                if _pattern(pattern).match(path) and (
                    len(pattern) > best_len or (len(pattern) == best_len and allow)
                ):
                    best_len, best_allow = len(pattern), allow
        return best_allow

    def crawl_delay(self, token: str) -> float | None:
        delays = [g.crawl_delay for g in self._select(token) if g.crawl_delay is not None]
        return max(delays) if delays else None

    def rule_count(self, token: str) -> int:
        return sum(len(g.rules) for g in self._select(token))
