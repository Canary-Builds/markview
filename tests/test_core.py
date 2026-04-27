from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vertexmarkdown_core as mv  # noqa: E402


def test_toggle_task_line_round_trip():
    line = "- [ ] ship release"
    assert mv.toggle_task_line(line, True) == "- [x] ship release"
    assert mv.toggle_task_line("- [X] ship release", False) == "- [ ] ship release"


def test_preprocess_tasks_skips_code_fences():
    src = "\n".join(
        [
            "- [ ] outside",
            "```",
            "- [ ] inside fence",
            "```",
        ]
    )
    out = mv.preprocess_tasks(src)
    assert 'data-task-line="0"' in out
    assert "inside fence" in out
    # fenced task line must not be converted into a checkbox input
    assert 'data-task-line="2"' not in out


def test_extract_headings_skips_fenced_code():
    src = "\n".join(
        [
            "# Real Heading",
            "```",
            "## Not A Real Heading",
            "```",
            "## Second Heading",
        ]
    )
    headings = mv.extract_headings(src)
    assert [h["title"] for h in headings] == ["Real Heading", "Second Heading"]
    assert [h["level"] for h in headings] == [1, 2]


def test_looks_like_csv_detects_separators():
    assert mv.looks_like_csv("a,b\n1,2\n") == (",", True)
    assert mv.looks_like_csv("a\tb\n1\t2\n") == ("\t", True)
    assert mv.looks_like_csv("single line only") == ("", False)


def test_csv_to_markdown_table():
    src = "name,score\nAlice,10\nBob,8\n"
    out = mv.csv_to_markdown_table(src, ",")
    expected = (
        "| name | score |\n"
        "| --- | --- |\n"
        "| Alice | 10 |\n"
        "| Bob | 8 |\n"
    )
    assert out == expected


def test_preprocess_transclusions_inlines_markdown_file(tmp_path: Path):
    (tmp_path / "child.md").write_text("# Child\n\nHello from child\n", encoding="utf-8")
    src = "Before\n\n![[child.md]]\n\nAfter"
    out = mv.preprocess_transclusions(src, tmp_path)
    assert "Hello from child" in out
    assert "Before" in out and "After" in out

