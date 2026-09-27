"""Ferramentas locais permitidas: sem shell, rede ou escrita arbitrária."""

import ast
import datetime as dt
import operator


class ToolError(ValueError):
    pass


def local_time(_arguments: dict) -> str:
    now = dt.datetime.now().astimezone()
    return now.isoformat(timespec="seconds")


def calculate(arguments: dict) -> str:
    expression = arguments.get("expression")
    if not isinstance(expression, str) or len(expression) > 120:
        raise ToolError("Informe uma expressão matemática curta.")
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 40:
            raise ToolError("Expressão muito complexa.")
        result = _eval_node(tree.body)
    except (SyntaxError, ZeroDivisionError, OverflowError, TypeError) as exc:
        raise ToolError("Expressão inválida ou operação não permitida.") from None
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ToolError("A expressão precisa produzir um número.")
    if abs(result) > 10**100:
        raise ToolError("Resultado excede o limite permitido.")
    return str(result)


_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        if isinstance(node.op, ast.Pow) and abs(_eval_node(node.right)) > 12:
            raise ToolError("Expoente excede o limite permitido.")
        return _BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand))
    raise ToolError("Operação não permitida.")


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "local_time",
            "description": "Consulta a data e hora local atual do aparelho.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Calcula uma expressão aritmética simples com segurança.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Ex.: (12+3)*4"}},
                "required": ["expression"], "additionalProperties": False,
            },
        },
    },
]


def run_tool(name: str, arguments: dict) -> str:
    if name == "local_time":
        return local_time(arguments)
    if name == "calculate":
        return calculate(arguments)
    raise ToolError("Essa ferramenta não está habilitada.")
