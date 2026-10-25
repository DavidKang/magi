import asyncio
from dataclasses import replace

import pytest
from textual.widgets import OptionList, Static

from builders import CHANGES, HUNK, OUTDATED, PR_ONE, PR_TWO, THREAD, board, settings_file
from tarkon.tui import app as app_module
from tarkon.tui.app import TarkonApp


async def review_popup(cache):
    pr_two = replace(PR_TWO, reviews=[*PR_TWO.reviews, CHANGES], threads=[THREAD, OUTDATED])
    opened, copied = [], []
    app = TarkonApp(load=lambda: board([PR_ONE, pr_two]), opener=opened.append, copier=copied.append, clock=lambda: 1000.0,
                         cache=cache, config_path=settings_file(cache))
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = lambda selector: str(app.screen.query_one(selector, Static).render())
        await pilot.press("4", "j", "c")
        assert isinstance(app.screen, app_module.ReviewScreen), "c opens the review comments of the selected PR"
        assert not app.check_action("pick_theme", ()), "the review popup blocks the theme key"
        assert app.screen.query_one(OptionList).option_count == 3, "the popup lists the review and every open thread"
        assert "brs#2" in str(app.screen.query_one("#review").border_title), "the popup title names the PR"
        prompts = [str(app.screen.query_one(OptionList).get_option_at_index(i).prompt) for i in range(3)]
        assert "Please split this" in prompts[0], "each thread in the list previews its first comment"
        assert "Rename qty to quantity" in prompts[1], "each thread in the list previews its first comment"
        assert "Typo" in prompts[2], "each thread in the list previews its first comment"
        assert prompts[1].splitlines() == ["order.rb:12", "carol · 2 comments", "Rename qty to quantity"], \
            "each thread shows file, author and description on their own lines"
        assert prompts[0].splitlines() == ["changes requested", "carol", "Please split this"], \
            "each thread shows file, author and description on their own lines"
        assert prompts[2].splitlines()[0] == "README.md · outdated", "an outdated thread says so in the list"
        assert any(b.key_display == "j/k" for b in app.screen.query_one(OptionList)._bindings.key_to_bindings.get("j", [])), \
            "the popup footer explains how to move"
        assert "Please split this" in text("#review-comments"), "a review shows its body without a diff"
        assert not app.screen.query_one("#review-diff-box").display, "a review shows its body without a diff"
        await pilot.press("j")
        assert "app/models/order.rb:12" in text("#review-place"), "j moves to the next thread and shows its file and line"
        assert app.screen.query_one("#review-diff-box").display, "the thread shows its diff"
        assert ".sum { |item|" in text("#review-diff"), "the thread shows its diff"
        assert text("#review-comments").index("Rename qty") < text("#review-comments").index("Done"), "the thread shows every comment in order"
        await pilot.press("enter")
        assert opened[-1] == THREAD["comments"][0]["url"], "enter opens the thread on GitHub"
        await pilot.press("y")
        assert copied[-1] == THREAD["comments"][0]["url"], "y copies the thread link"
        await pilot.press("j")
        assert "outdated" in text("#review-place"), "an outdated thread says so"
        assert "README.md" in text("#review-place"), "an outdated thread says so"
        await pilot.press("q")
        assert not isinstance(app.screen, app_module.ReviewScreen), "q closes the popup without quitting"
        assert app.is_running, "q closes the popup without quitting"
        await pilot.press("k", "c")
        assert not isinstance(app.screen, app_module.ReviewScreen), "c on a PR without comments keeps the board"
        await pilot.press("j")
        detail = str(app.query_one("#detail", Static).render()).splitlines()
        row = next(i for i, line in enumerate(detail) if "c to open" in line)
        await pilot.click("#detail", offset=(10, row))
        assert isinstance(app.screen, app_module.ReviewScreen), "clicking the comments line in the detail opens the popup"
        await pilot.press("escape")
        assert not isinstance(app.screen, app_module.ReviewScreen), "escape closes the popup"


@pytest.mark.usefixtures("aliases")
def test_review_popup(cache):
    asyncio.run(review_popup(cache))


async def long_diff(cache):
    hunk = HUNK.replace("item.price * item.qty", " + ".join(f"item.price_{n} * item.qty_{n}" for n in range(12)))
    thread = {**THREAD, "comments": [{**comment, "diffHunk": hunk} for comment in THREAD["comments"]]}
    pr_two = replace(PR_TWO, threads=[thread])
    app = TarkonApp(load=lambda: board([PR_ONE, pr_two]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                   config_path=settings_file(cache))
    async with app.run_test(size=(100, 30)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("4", "j", "c")
        await pilot.pause()
        box = app.screen.query_one("#review-diff-box")
        assert box.max_scroll_x == 0, "a long diff line wraps inside the popup instead of scrolling sideways"
        assert "item.qty_11 }" in str(app.screen.query_one("#review-diff", Static).render()), "the wrapped diff keeps the whole line"
        await pilot.resize_terminal(70, 30)
        await pilot.pause()
        width = box.scrollable_content_region.width
        lines = str(app.screen.query_one("#review-diff", Static).render()).splitlines()
        assert (box.max_scroll_x, max(len(line) for line in lines)) == (0, width), "a narrower terminal wraps the diff again to the new width"


@pytest.mark.usefixtures("default_theme")
def test_long_diff_lines_wrap(cache):
    asyncio.run(long_diff(cache))
