from __future__ import annotations

import ast
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

EXCLUDED_DIRS = {".git", ".hg", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv", "build", "dist", "htmlcov", "node_modules", "target", "venv"}


@dataclass(frozen=True)
class FunctionMetric:
    name: str
    file: str
    start_line: int
    end_line: int
    complexity: int
    coverage: float | None
    crap: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.value = 1

    def visit_If(self, node: ast.If) -> None:
        self.value += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.value += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.value += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.value += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.value += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.value += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.value += len(node.handlers)
        self.generic_visit(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.value += len(node.handlers)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.value += len(node.cases)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.value += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested functions have their own metric.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Lambdas have no stable qualified name in coverage reports.
        return


def _function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = ComplexityVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.value


def _walk_functions(body: Sequence[ast.stmt], prefix: str = "") -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}.{statement.name}" if prefix else statement.name
            yield name, statement
            yield from _walk_functions(statement.body, name)
        elif isinstance(statement, ast.ClassDef):
            name = f"{prefix}.{statement.name}" if prefix else statement.name
            yield from _walk_functions(statement.body, name)


def extract_functions(path: Path) -> list[FunctionMetric]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    metrics: list[FunctionMetric] = []
    for name, node in _walk_functions(tree.body):
        end_line = getattr(node, "end_lineno", node.lineno)
        metrics.append(
            FunctionMetric(
                name=name,
                file=path.as_posix(),
                start_line=node.lineno,
                end_line=end_line,
                complexity=_function_complexity(node),
                coverage=None,
                crap=None,
            )
        )
    return metrics


def discover_files(root: Path, filters: Sequence[str] = ()) -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            if filename.startswith("test_") or filename.endswith("_test.py"):
                continue
            path = Path(directory, filename)
            relative = path.relative_to(root).as_posix()
            if filters and not any(fragment in relative for fragment in filters):
                continue
            files.append(path)
    return files


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def load_coverage(path: Path) -> dict[str, tuple[set[int], set[int]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[set[int], set[int]]] = {}
    for filename, data in payload.get("files", {}).items():
        executed = {int(line) for line in data.get("executed_lines", [])}
        missing = {int(line) for line in data.get("missing_lines", [])}
        out[normalize_path(filename)] = (executed, missing)
    return out


def _coverage_for_file(coverage: dict[str, tuple[set[int], set[int]]], filename: str) -> tuple[set[int], set[int]] | None:
    normalized = normalize_path(filename)
    if normalized in coverage:
        return coverage[normalized]
    candidates = [value for key, value in coverage.items() if key.endswith("/" + normalized) or normalized.endswith("/" + key)]
    return candidates[0] if len(candidates) == 1 else None


def score(complexity: int, coverage_percent: float) -> float:
    uncovered = 1.0 - coverage_percent / 100.0
    return complexity * complexity * uncovered**3 + complexity


def apply_coverage(metrics: Iterable[FunctionMetric], coverage: dict[str, tuple[set[int], set[int]]]) -> list[FunctionMetric]:
    out: list[FunctionMetric] = []
    for metric in metrics:
        line_data = _coverage_for_file(coverage, metric.file)
        if line_data is None:
            out.append(metric)
            continue
        executed, missing = line_data
        executable = {line for line in executed | missing if metric.start_line <= line <= metric.end_line}
        covered = {line for line in executed if line in executable}
        coverage_percent = 0.0 if not executable else 100.0 * len(covered) / len(executable)
        out.append(
            FunctionMetric(
                **{**metric.to_dict(), "coverage": coverage_percent, "crap": score(metric.complexity, coverage_percent)}
            )
        )
    return out


def analyze(root: Path, coverage_path: Path | None, filters: Sequence[str] = ()) -> list[FunctionMetric]:
    metrics: list[FunctionMetric] = []
    for path in discover_files(root, filters):
        metrics.extend(extract_functions(path))
    if coverage_path is not None and coverage_path.exists():
        metrics = apply_coverage(metrics, load_coverage(coverage_path))
    return sorted(metrics, key=lambda metric: (metric.crap is None, -(metric.crap or -math.inf), metric.file, metric.name))


def run_test_command(command: str, root: Path) -> None:
    completed = subprocess.run(command, cwd=root, shell=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"test command failed with exit code {completed.returncode}: {command}")


def format_report(metrics: Sequence[FunctionMetric]) -> str:
    header = f"{'Function':36} {'File':44} {'CC':>4} {'Cov%':>7} {'CRAP':>8}"
    lines = ["CRAP Report", "===========", header, "-" * len(header)]
    for metric in metrics:
        coverage = "N/A" if metric.coverage is None else f"{metric.coverage:.1f}%"
        crap = "N/A" if metric.crap is None else f"{metric.crap:.1f}"
        lines.append(f"{metric.name[:36]:36} {metric.file[:44]:44} {metric.complexity:4d} {coverage:>7} {crap:>8}")
    return "\n".join(lines) + "\n"
