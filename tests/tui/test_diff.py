import re

from builders import HUNK
from tarkon.tui import entries


def test_diff_rendering():
    diff = entries.diff_text(HUNK, "app/models/order.rb")
    lines = diff.plain.splitlines()
    assert lines[0].strip() == "@@ -1,5 +1,5 @@", "diff keeps the hunk header"
    assert re.match(r"\s*1\s+1\s+def total", lines[1]) is not None, "diff numbers context lines on both sides"
    assert re.match(r"\s*3\s+-\s+\.sum\(&:price\)", lines[3]) is not None, "diff numbers a removed line on the old side"
    assert re.match(r"\s*3\s+\+\s+\.sum \{", lines[4]) is not None, "diff numbers an added line on the new side"
    assert lines[1].startswith("1 1  def total"), "the line numbers take only the width they need"
    assert lines[4].startswith("  3 +    .sum {"), "the line numbers take only the width they need"
    assert lines[0] == "    @@ -1,5 +1,5 @@", "the line numbers take only the width they need"
    added_only = entries.diff_text("@@ -0,0 +1,2 @@\n+first\n+second", "notes.md").plain.splitlines()
    assert [line.rstrip() for line in added_only[1:]] == ["1 +first", "2 +second"], "a hunk of only additions shows a single number column"
    assert added_only[0] == "  @@ -0,0 +1,2 @@", "a hunk of only additions shows a single number column"
    added = diff.plain.index("+    .sum {")
    assert any(span.start <= added < span.end and str(span.style).endswith(f"on {entries.DIFF_BACKGROUNDS['+']}") for span in diff.spans), \
        "added lines have a green background, removed ones red"
    assert entries.DIFF_BACKGROUNDS["+"] != entries.DIFF_BACKGROUNDS["-"], "added lines have a green background, removed ones red"
