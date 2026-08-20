# crap4python

`crap4python` calculates the Change Risk Anti-Pattern metric for each Python function and method.

```text
CRAP = CC² × (1 - coverage)³ + CC
```

It uses the Python AST for cyclomatic complexity and the JSON report from `coverage.py` for executable-line coverage.

## Install

```bash
pipx install git+https://github.com/lukasa1993/crap4python.git
```

## Run

From a Python project:

```bash
crap4python --fail-over 6
```

The default verification command is:

```bash
coverage run -m pytest && coverage json -o target/coverage/coverage.json
```

Use another command when required:

```bash
crap4python --test-command "coverage run -m unittest && coverage json -o target/coverage/coverage.json"
```

Read an existing report without running tests:

```bash
crap4python --no-test --coverage target/coverage/coverage.json
```

Use `--json` for machine-readable output. Path fragments supplied as positional arguments limit the analyzed files.

## Complexity rules

The base complexity is `1`. The tool adds decision points for `if`, conditional expressions, loops, boolean operands, exception handlers, `match` cases, and comprehensions.

## Development

```bash
python -m pip install -e . pytest coverage
pytest -q
```
