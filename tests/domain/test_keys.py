from builders import make_pr
from magi.domain.keys import title_keys_in


def test_title_keys_join_bracketed_and_project_keys():
    pr = make_pr(title="[RED-7] fix kame-12 and [ribbon-1]", head_ref_name="KAME-30-kaioken")
    assert title_keys_in(pr, "KAME") == {"RED-7", "KAME-12", "KAME-30"}, \
        "any bracketed uppercase key counts, plus the project's keys in the title or branch, upper-cased"
