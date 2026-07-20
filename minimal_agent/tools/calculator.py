from __future__ import annotations

import ast
import math
import operator

from pydantic import BaseModel, ConfigDict, Field

from minimal_agent.models import ToolResult

from .base import AgentTool


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(
        min_length=1,
        max_length=200,
        description="只包含数字、括号和基本算术运算符的表达式",
    )


class CalculatorTool(AgentTool):
    name = "calculator"
    description = "安全计算数学表达式，支持加减乘除、幂、取余和括号。"
    args_model = CalculatorArgs

    _binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    async def execute(
        self, arguments: CalculatorArgs, *, session_id: str
    ) -> ToolResult:
        del session_id
        try:
            tree = ast.parse(arguments.expression, mode="eval")
            value = self._evaluate(tree.body)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("计算结果不是有限数值")
            if abs(float(value)) > 1e100:
                raise ValueError("计算结果过大")
            return ToolResult(
                ok=True,
                tool_name=self.name,
                data={"expression": arguments.expression, "result": value},
            )
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError) as error:
            return ToolResult(
                ok=False,
                tool_name=self.name,
                error_code="INVALID_EXPRESSION",
                message=str(error),
            )

    def _evaluate(self, node: ast.AST, depth: int = 0) -> int | float:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary_ops:
            left = self._evaluate(node.left, depth + 1)
            right = self._evaluate(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(float(right)) > 100:
                raise ValueError("指数过大")
            return self._binary_ops[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary_ops:
            return self._unary_ops[type(node.op)](
                self._evaluate(node.operand, depth + 1)
            )
        raise ValueError("表达式包含不允许的内容")
