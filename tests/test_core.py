from pathlib import Path

from crap4python.core import analyze, extract_functions, score


def test_score() -> None:
    assert score(10, 50.0) == 22.5
    assert score(10, 100.0) == 10.0


def test_extract_and_map_coverage(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def choose(value):\n"
        "    if value and value > 1:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        '{"files":{"sample.py":{"executed_lines":[1,2,4],"missing_lines":[3]}}}',
        encoding="utf-8",
    )
    metric = analyze(tmp_path, coverage)[0]
    assert metric.name == "choose"
    assert metric.complexity == 3
    assert metric.coverage == 75.0


def test_nested_method_names(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("class A:\n    def run(self):\n        return 1\n", encoding="utf-8")
    assert extract_functions(source)[0].name == "A.run"
