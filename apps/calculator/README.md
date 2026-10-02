# Calculator

A first-party 480×272 calculator using Python 3.11+ and Tkinter (`python3-tk`
on Debian 13). No network, storage, private data or third-party Python packages.
Launch with `python3 /path/to/calculator/main.py`; the manifest-v1 launcher uses
`main.py` from the installed package. App Center lists the package with installation disabled until device lifecycle
verification is complete.

Type numbers, decimal points, scientific exponents (`e`), `+ - * /`, parentheses and `%`. Percent divides its
operand by 100: `200*10%` is 20. Operations follow ordinary precedence. The ± key
negates the complete grouped expression. C/Delete clears; Backspace removes one
character. `=` evaluates; repeated `=` evaluates the same expression. Operators
after a result continue with its full decimal precision; a digit starts fresh.

Arrows move across the 4×5 keypad; Tab/Shift+Tab reach every control, including
parentheses. Enter/Space activates the focused control. Escape exits. Mouse and
touch are optional. Long expressions show their trailing input; results use 12
significant visible digits and scientific notation when necessary. Calculation
uses 28 decimal digits; input is limited to 120 characters and nesting to 24.
Malformed expressions and divide-by-zero leave the previous result visible.

Drawing is event-driven through Tk's off-screen window composition. Tk has no
portable per-window VSync request; synchronized presentation relies on the Shell's
verified device compositor. Desktop checks do not establish device scanout.

Run `python3 tools/scoped_tests.py --app apps/calculator --run` from the repo root.
