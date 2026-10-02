"""Bounded decimal expression parser. No eval, binary floats or executable input."""
from decimal import Decimal, DecimalException, localcontext
import re

MAX_INPUT = 120
TOKEN = re.compile(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?|[()+*/%\-]')


class CalculationError(ValueError):
    """A user-facing arithmetic/input error."""


def evaluate(expression):
    compact = expression.replace(' ', '')
    if not compact or len(compact) > MAX_INPUT:
        raise CalculationError('Enter an expression (up to 120 characters)')
    tokens = TOKEN.findall(compact)
    if ''.join(tokens) != compact:
        raise CalculationError('Use numbers and arithmetic operators')
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else None

    def consume():
        nonlocal position
        value = peek()
        position += 1
        return value

    def primary(depth):
        if depth > 24:
            raise CalculationError('Too many nested parentheses')
        token = consume()
        if token in ('+', '-'):
            result = primary(depth + 1)
            result = -result if token == '-' else result
        elif token == '(':
            result = addition(depth + 1)
            if consume() != ')':
                raise CalculationError('Close the parentheses')
        elif token is not None and token[0] in '.0123456789':
            result = Decimal(token)
        else:
            raise CalculationError('Expected a number')
        while peek() == '%':
            consume()
            result /= 100
        return result

    def multiplication(depth):
        result = primary(depth)
        while peek() in ('*', '/'):
            operator = consume()
            right = primary(depth)
            if operator == '/' and right == 0:
                raise CalculationError('Cannot divide by zero')
            result = result * right if operator == '*' else result / right
        return result

    def addition(depth):
        result = multiplication(depth)
        while peek() in ('+', '-'):
            operator = consume()
            right = multiplication(depth)
            result = result + right if operator == '+' else result - right
        return result

    try:
        with localcontext() as context:
            context.prec = 28
            context.Emax = 99
            context.Emin = -99
            result = addition(0)
            if peek() is not None:
                raise CalculationError('Check the expression')
            if not result.is_finite() or abs(result) > Decimal('1e99'):
                raise CalculationError('Result is too large')
            return result
    except DecimalException as error:
        raise CalculationError('Result is outside the supported range') from error


def format_result(value):
    if value == 0:
        return '0'
    with localcontext() as context:
        context.prec = 12
        rounded = +value
        if rounded.adjusted() >= 12 or rounded.adjusted() < -8:
            mantissa, exponent = format(rounded, 'E').split('E')
            return mantissa.rstrip('0').rstrip('.') + 'e' + str(int(exponent))
        return format(rounded, 'f').rstrip('0').rstrip('.') if '.' in format(rounded, 'f') else format(rounded, 'f')


class Calculator:
    def __init__(self):
        self.expression = ''
        self.result = '0'
        self.error = ''
        self.evaluated = False

    def press(self, key):
        self.error = ''
        if key == 'C':
            self.expression, self.result, self.evaluated = '', '0', False
        elif key == 'Backspace':
            self.expression = self.expression[:-1]
            self.evaluated = False
        elif key == '=':
            try:
                self.result = format_result(evaluate(self.expression))
                self.evaluated = True
            except CalculationError as error:
                self.error = str(error)
        elif key == '±':
            # Negate the complete input, preserving its grouping and precedence.
            if self.expression:
                candidate = '-(' + self.expression + ')'
                if len(candidate) <= MAX_INPUT:
                    self.expression = candidate
                    self.evaluated = False
        elif key in '0123456789.eE+-*/()%':
            if self.evaluated:
                if key in '+-*/%':
                    # Keep decimal precision when chaining; do not parse display
                    # scientific notation or truncate to its 12 visible digits.
                    self.expression = str(evaluate(self.expression))
                else:
                    self.expression = ''
                self.evaluated = False
            if len(self.expression) < MAX_INPUT:
                self.expression += key
            else:
                self.error = 'Input limit: 120 characters'
