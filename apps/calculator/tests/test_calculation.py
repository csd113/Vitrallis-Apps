from decimal import Decimal
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calculation import Calculator, CalculationError, evaluate, format_result


class ArithmeticTests(unittest.TestCase):
    def test_decimal_and_precedence(self):
        for expression, answer in [('0.1+0.2', '.3'), ('2+3*4', '14'),
                                   ('(2+3)*4', '20'), ('200*10%', '20'),
                                   ('-3*-2', '6'), ('1/8', '.125'), ('1--2', '3'), ('1e3', '1000')]:
            self.assertEqual(evaluate(expression), Decimal(answer))

    def test_invalid_zero_and_bounded_input(self):
        for expression in ('', '1/0', '1/(2-2)', '1..2', '2(3)', '()', '1+',
                           '1e999', '__import__("os")', '('*30+'1'+')'*30, '9'*121,
                           '9'*100+'*9'*10):
            with self.subTest(expression=expression), self.assertRaises(CalculationError):
                evaluate(expression)

    def test_formatting_and_repeated_evaluation(self):
        self.assertEqual(format_result(evaluate('0.1+0.2')), '0.3')
        self.assertEqual(format_result(evaluate('1000000000000')), '1e12')
        self.assertEqual(format_result(evaluate('1/3')), '0.333333333333')
        model = Calculator()
        for key in '1/3==': model.press(key)
        self.assertEqual(model.result, '0.333333333333')
        for key in '*3=': model.press(key)
        self.assertEqual(model.result, '1')
        model.press('2')
        self.assertEqual(model.expression, '2')
        model.press('±'); model.press('=')
        self.assertEqual(model.result, '-2')
        model.press('C')
        self.assertEqual((model.expression, model.result), ('', '0'))
