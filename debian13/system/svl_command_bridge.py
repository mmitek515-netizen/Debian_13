"""Read-only SVL command router for the authenticated Debian 13 HTTP API.

SVL does not execute arbitrary shell commands, grant root permissions or start
agents. Those actions require separate, explicit, verified integrations.
"""
from __future__ import annotations

import json
import shlex
from collections.abc import Callable

from svl_kernel import SVLSystemKernel, TopologicalInfinityEngine


class SVLCommandError(ValueError):
    pass


class SVLCommandProcessor:
    COMMANDS = ("status", "metryka", "diagnostyka", "integracje", "agenci", "zadania", "pomoc")

    def __init__(self, *, diagnostics: Callable[[], dict] | None = None,
                 integrations: Callable[[], dict] | None = None,
                 agents: Callable[[], dict] | None = None,
                 tasks: Callable[[], dict] | None = None):
        self.kernel = SVLSystemKernel()
        self._readers = {
            "diagnostyka": diagnostics,
            "integracje": integrations,
            "agenci": agents,
            "zadania": tasks,
        }

    def process(self, command: str) -> dict:
        if not isinstance(command, str) or not 1 <= len(command.strip()) <= 200:
            raise SVLCommandError("Command must contain 1-200 characters")
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise SVLCommandError("Invalid command quoting") from exc
        if not parts or parts[0] not in self.COMMANDS:
            raise SVLCommandError("Command not allowed; use 'pomoc'")
        action, args = parts[0], parts[1:]
        if action == "pomoc" and not args:
            result = {"allowedCommands": list(self.COMMANDS), "execution": "read_only"}
        elif action == "status" and not args:
            result = json.loads(self.kernel.generate_system_status_report())
        elif action == "metryka" and len(args) == 2:
            try:
                start, end = float(args[0]), float(args[1])
                engine = TopologicalInfinityEngine(start, end)
            except ValueError as exc:
                raise SVLCommandError("Metric endpoints must be numeric and not NaN") from exc
            result = {"start": args[0], "end": args[1],
                      "compactStart": engine.compact_start,
                      "compactEnd": engine.compact_end,
                      "metricC": round(engine.calculate_metric_c(), 6)}
        elif action in self._readers and not args:
            reader = self._readers[action]
            if reader is None:
                raise SVLCommandError("This integration is unavailable")
            result = reader()
        else:
            raise SVLCommandError("Invalid number of arguments; use 'pomoc'")
        return {"processor": "SVL", "version": self.kernel.sys_version.value,
                "command": action, "execution": "read_only", "result": result}
