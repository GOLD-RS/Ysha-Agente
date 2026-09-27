"""Política explícita para as ferramentas locais atualmente permitidas."""

import json

from .tools import ToolError, run_tool


class ToolPolicy:
    """Allow only the fixed, side-effect-limited tools shipped with the agent."""

    ARGUMENT_KEYS = {
        "local_time": frozenset(),
        "calculate": frozenset({"expression"}),
    }
    INVALID_RESULT = "Erro: argumentos inválidos ou ferramenta não permitida."

    def execute_call(self, call) -> str:
        if not isinstance(call, dict):
            return self.INVALID_RESULT
        function = call.get("function")
        if not isinstance(function, dict):
            return self.INVALID_RESULT
        name = function.get("name")
        raw_arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(raw_arguments, str):
            return self.INVALID_RESULT
        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            return self.INVALID_RESULT
        if not isinstance(arguments, dict) or name not in self.ARGUMENT_KEYS:
            return self.INVALID_RESULT
        if set(arguments) != self.ARGUMENT_KEYS[name]:
            return self.INVALID_RESULT
        if name == "calculate" and not isinstance(arguments.get("expression"), str):
            return self.INVALID_RESULT
        try:
            return run_tool(name, arguments)
        except (ToolError, TypeError, ValueError, KeyError):
            return self.INVALID_RESULT
