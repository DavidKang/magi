from builders import PR_ONE
from magi.domain import histories, review


def test_kept_histories():
    kept = histories.kept_histories({"gone": ["merged pr"], "old": ["forgotten pr"]}, [{"group": "gone"}])
    assert kept == {"gone": ["merged pr"]}, "a saved history stays while a change still shows it"


def test_pr_histories():
    saved = {PR_ONE.url: ["stale"], "https://github.com/acme/app/pull/8": ["merged pr"]}
    found = histories.pr_histories([PR_ONE], saved)
    assert found == {PR_ONE.url: review.pr_events(PR_ONE), "https://github.com/acme/app/pull/8": ["merged pr"]}, \
        "a pr on the board tells its own history, and one that left keeps the history saved for it"
