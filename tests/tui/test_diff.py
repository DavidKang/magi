import re

import pytest
from rich.cells import cell_len

from builders import HUNK
from tarkon.tui import entries, theme


def test_diff_rendering():
    diff = entries.diff_text(HUNK, "app/models/order.rb", 80)
    lines = diff.plain.splitlines()
    assert lines[0].strip() == "@@ -1,5 +1,5 @@", "diff keeps the hunk header"
    assert re.match(r"\s*1\s+1\s+def total", lines[1]) is not None, "diff numbers context lines on both sides"
    assert re.match(r"\s*3\s+-\s+\.sum\(&:price\)", lines[3]) is not None, "diff numbers a removed line on the old side"
    assert re.match(r"\s*3\s+\+\s+\.sum \{", lines[4]) is not None, "diff numbers an added line on the new side"
    assert lines[1].startswith("1 1  def total"), "the line numbers take only the width they need"
    assert lines[4].startswith("  3 +    .sum {"), "the line numbers take only the width they need"
    assert lines[0] == "    @@ -1,5 +1,5 @@", "the line numbers take only the width they need"
    added_only = entries.diff_text("@@ -0,0 +1,2 @@\n+first\n+second", "notes.md", 80).plain.splitlines()
    assert [line.rstrip() for line in added_only[1:]] == ["1 +first", "2 +second"], "a hunk of only additions shows a single number column"
    assert added_only[0] == "  @@ -0,0 +1,2 @@", "a hunk of only additions shows a single number column"
    added = diff.plain.index("+    .sum {")
    assert any(span.start <= added < span.end and str(span.style).endswith(f"on {entries.DIFF_BACKGROUNDS['+']}") for span in diff.spans), \
        "added lines have a green background, removed ones red"
    assert entries.DIFF_BACKGROUNDS["+"] != entries.DIFF_BACKGROUNDS["-"], "added lines have a green background, removed ones red"


@pytest.mark.usefixtures("default_theme")
def test_context_lines_take_the_theme_background():
    theme.use_theme("nerv")
    diff = entries.diff_text(HUNK, "app/models/order.rb", 80)
    context = diff.plain.index("def total")
    assert any(span.start <= context < span.end and str(span.style).endswith(f"on {theme.THEMES['nerv']['bg']}") for span in diff.spans), \
        "context lines sit on the theme's background, not the default theme's"


def test_diff_wraps_long_lines_to_its_width():
    code = "total = " + " + ".join(f"item_{n}.price" for n in range(6))
    diff = entries.diff_text(f"@@ -1,2 +1,2 @@\n context\n+{code}", "app.rb", 30)
    lines = diff.plain.splitlines()
    assert [len(line) for line in lines[1:]] == [30] * (len(lines) - 1), "a diff fills the width it is given and never runs past it"
    added = lines[2:]
    assert added[0].startswith("  2 +") and all(line.startswith(" " * 5) for line in added[1:]), \
        "a long line goes on below its own code, leaving the numbers and sign column blank"
    assert " ".join(line[5:].strip() for line in added) == code, "a long line wraps between words without losing any of its code"
    last = diff.plain.rindex(added[-1].rstrip()[-1])
    assert any(span.start <= last < span.end and str(span.style).endswith(f"on {entries.DIFF_BACKGROUNDS['+']}") for span in diff.spans), \
        "a wrapped added line keeps its green background"


def test_diff_wraps_long_hunk_headers():
    header = "@@ -10,2 +10,2 @@ def reconcile_every_settlement_against_the_ledger(batch)"
    lines = entries.diff_text(f"{header}\n context\n+added", "app.rb", 30).plain.splitlines()
    heading = lines[:-2]
    assert all(len(line) <= 30 for line in lines), "a long hunk header wraps to the width instead of being cut off"
    assert all(line.startswith(" " * 4) for line in heading), "a wrapped hunk header keeps clear of the number columns"
    assert re.sub(r"\s", "", "".join(heading)) == re.sub(r"\s", "", header), "a wrapped hunk header keeps all of its text"


def test_diff_pads_wide_characters_by_cell():
    lines = entries.diff_text("@@ -1,1 +1,1 @@\n-名前\n+氏名を変更", "notes.md", 20).plain.splitlines()
    assert [cell_len(line) for line in lines[1:]] == [20, 20], "a line with wide characters fills the width and no more"
