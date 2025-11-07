"""Safe expression evaluator for achievement conditions.

This module provides a safe alternative to eval() for evaluating achievement
conditions. It uses AST parsing to only allow safe operations like comparisons,
attribute access, and basic arithmetic.
"""

import ast
import operator
from typing import Any


# Allowed operators mapping
SAFE_OPERATORS = {
    # Comparison operators
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    # Boolean operators
    ast.And: operator.and_,
    ast.Or: operator.or_,
    ast.Not: operator.not_,
    # Arithmetic operators
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    # Unary operators
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    # Membership
    ast.In: lambda x, y: x in y,
    ast.NotIn: lambda x, y: x not in y,
}


class SafeEvaluator:
    """Safe expression evaluator using AST.

    Only allows:
    - Comparisons (>, <, >=, <=, ==, !=)
    - Boolean operators (and, or, not)
    - Arithmetic operators (+, -, *, /, //, %, **)
    - Attribute access (e.g., score.pp)
    - Subscript access (e.g., list[0])
    - Constants (numbers, strings, None, True, False)
    - Membership tests (in, not in)

    Disallows:
    - Function calls (except whitelisted)
    - Imports
    - Assignments
    - Comprehensions
    - Lambda functions
    """

    def __init__(self, allowed_names: dict[str, Any]):
        """Initialize evaluator with allowed variable names.

        Args:
            allowed_names: Dictionary of variable names and their values
                          that can be used in expressions
        """
        self.allowed_names = allowed_names

    def evaluate(self, expression: str) -> Any:
        """Safely evaluate an expression.

        Args:
            expression: String expression to evaluate

        Returns:
            Result of the expression evaluation

        Raises:
            ValueError: If expression contains unsafe operations
            SyntaxError: If expression has invalid syntax
        """
        try:
            # Parse the expression into an AST
            tree = ast.parse(expression, mode='eval')

            # Evaluate the AST
            return self._eval_node(tree.body)

        except SyntaxError as e:
            raise SyntaxError(f"Invalid expression syntax: {e}") from e

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate an AST node."""

        # Constants (numbers, strings, None, True, False)
        if isinstance(node, ast.Constant):
            return node.value

        # For backwards compatibility with Python < 3.8
        if isinstance(node, (ast.Num, ast.Str)):
            return node.n if isinstance(node, ast.Num) else node.s

        if isinstance(node, ast.NameConstant):
            return node.value

        # Variable names
        if isinstance(node, ast.Name):
            if node.id not in self.allowed_names:
                raise ValueError(f"Access to variable '{node.id}' is not allowed")
            return self.allowed_names[node.id]

        # Attribute access (e.g., score.pp)
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value)
            try:
                return getattr(obj, node.attr)
            except AttributeError as e:
                raise ValueError(f"Attribute access error: {e}") from e

        # Subscript access (e.g., list[0])
        if isinstance(node, ast.Subscript):
            obj = self._eval_node(node.value)
            index = self._eval_node(node.slice)
            try:
                return obj[index]
            except (KeyError, IndexError, TypeError) as e:
                raise ValueError(f"Subscript access error: {e}") from e

        # Binary operations (e.g., a + b, a > b)
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op = SAFE_OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"Binary operator {type(node.op).__name__} is not allowed")
            try:
                return op(left, right)
            except Exception as e:
                raise ValueError(f"Binary operation error: {e}") from e

        # Unary operations (e.g., -x, not x)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op = SAFE_OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unary operator {type(node.op).__name__} is not allowed")
            try:
                return op(operand)
            except Exception as e:
                raise ValueError(f"Unary operation error: {e}") from e

        # Comparison operations (e.g., a < b, a == b)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)

            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                op_func = SAFE_OPERATORS.get(type(op))
                if op_func is None:
                    raise ValueError(f"Comparison operator {type(op).__name__} is not allowed")

                try:
                    result = op_func(left, right)
                except Exception as e:
                    raise ValueError(f"Comparison error: {e}") from e

                if not result:
                    return False
                left = right

            return True

        # Boolean operations (and, or)
        if isinstance(node, ast.BoolOp):
            op = SAFE_OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError(f"Boolean operator {type(node.op).__name__} is not allowed")

            values = [self._eval_node(value) for value in node.values]

            # Implement short-circuit evaluation
            if isinstance(node.op, ast.And):
                for value in values:
                    if not value:
                        return False
                return True
            elif isinstance(node.op, ast.Or):
                for value in values:
                    if value:
                        return True
                return False

        # If we get here, the node type is not allowed
        raise ValueError(
            f"Expression contains unsafe operation: {type(node).__name__}. "
            "Only comparisons, boolean operations, arithmetic, and attribute access are allowed."
        )


def safe_eval(expression: str, allowed_names: dict[str, Any]) -> Any:
    """Safely evaluate an expression with given variables.

    This is a convenience function that creates a SafeEvaluator and evaluates
    the expression in one call.

    Args:
        expression: String expression to evaluate
        allowed_names: Dictionary of variable names and values

    Returns:
        Result of the expression evaluation

    Raises:
        ValueError: If expression contains unsafe operations
        SyntaxError: If expression has invalid syntax

    Example:
        >>> safe_eval("score.pp > 100", {"score": score_obj})
        True
        >>> safe_eval("stats.username == 'player1'", {"stats": player_obj})
        False
    """
    evaluator = SafeEvaluator(allowed_names)
    return evaluator.evaluate(expression)
