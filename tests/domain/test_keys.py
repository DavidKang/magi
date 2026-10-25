from builders import make_pr
from magi.domain.keys import title_keys_in


def test_title_keys_join_bracketed_and_project_keys():
    pr = make_pr(title="[OPS-7] fix acme-12 and [lower-1]", head_ref_name="ACME-30-branch")
    assert title_keys_in(pr, "ACME") == {"OPS-7", "ACME-12", "ACME-30"}, \
        "any bracketed uppercase key counts, plus the project's keys in the title or branch, upper-cased"
