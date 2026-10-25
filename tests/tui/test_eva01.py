import asyncio
import datetime as dt

import pytest
from rich.console import Console
from textual.color import Color

from builders import SETTINGS, board, make_pr, settings_file
from magi.tui import theme
from magi.tui.app import MagiApp

# Unit-01 in nerv-ui's tokens: purple armour, LCD green trim, nerv white text.
EVA01 = {"bg": "#000000", "fg": "#e0e0e0", "accent": "#39ff14", "line": "#9933ff", "focus": "#39ff14", "bad": "#ff0000", "ok": "#39ff14",
         "warn": "#ff9900"}


def start(cache, pr):
    return MagiApp(load=lambda: board([pr]), opener=print, copier=print, clock=lambda: 1000.0, cache=cache,
                    config_path=settings_file(cache, {**SETTINGS, "theme": "eva01"}))


def test_eva01_palette():
    assert {key: theme.THEMES["eva01"][key] for key in EVA01} == EVA01, "EVA 01 wears Unit-01's colours"


async def eva01(cache, pr):
    app = start(cache, pr)
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.has_class("nerv") and app.query_one("#nerv-logo").display, "EVA 01 draws the NERV frame"
        assert str(app.query_one("#panel-prs").border_title) == "04-SORTIES 1", "EVA 01 names the boxes in NERV's words"
        for key, tone in (("attention", "focus"), ("prs", "line")):
            box = app.query_one(f"#panel-{key}")
            colours = [box.query_one(".pbody").styles.border_left[1], *[edge.styles.color for edge in box.query(".ptitle .edge")]]
            assert colours == [Color.parse(EVA01[tone])] * 3, f"EVA 01 draws the {key} box {tone == 'focus' and 'green, focused' or 'purple'}"
        assert app.query_one("#panel-prs .ptitle .name").styles.color == Color.parse(EVA01["accent"]), "EVA 01 titles its boxes in green"
        key = app.query_one("FooterKey")
        assert key.region.x == app.query_one("#panel-attention").region.x, "EVA 01 lines its footer up with the boxes"
        description = key.get_component_rich_style("footer-key--description")
        assert (description.color.triplet.hex, key.styles.background) == (EVA01["accent"], Color.parse(EVA01["bg"])), \
            "EVA 01 writes the footer in green on black, since no text reads well on purple"
        assert key.get_component_styles("footer-key--description").padding.left == 1, "EVA 01 sets the footer text off its key"
        assert str(app.query_one("#status").render()) == f"EVA-01 · PILOT ALICE · SYNC {dt.datetime.fromtimestamp(1000.0):%H:%M}", \
            "EVA 01 names you, by your GitHub user, as its pilot"
        shown, stripe = app.query_one("#condition").render(), app.query_one("#bar").content
        return shown.plain, [str(span.style.foreground) for span in shown.spans], \
            stripe.plain[:8], [stripe.get_style_at_offset(Console(), n).color.triplet.hex for n in range(8)]


@pytest.mark.usefixtures("default_theme")
@pytest.mark.parametrize("pr, label, tone", [
    (make_pr(review_decision="APPROVED", ci="passing", mergeable="MERGEABLE"), "SYNC STABLE", "ok"),
    (make_pr(ci="passing", mergeable="MERGEABLE"), "SYNC UNSTABLE", "warn"),
    (make_pr(), "BERSERK", "bad")])
def test_eva01_frame(cache, pr, label, tone):
    shown, colours, stripe, pieces = asyncio.run(eva01(cache, pr))
    assert (shown, colours) == (f"■ {label}", [str(Color.parse(EVA01[tone]))] * 2), "EVA 01 reads the alert level as Unit-01's sync"
    calm = tone != "bad"
    assert stripe == ("━" * 8 if calm else "◢◤" * 4), "EVA 01 tops the screen with a quiet line, and NERV's hazard stripe only when berserk"
    assert pieces == [EVA01["line" if calm else "bad"]] * 8, "the quiet line is purple, the berserk stripe red"
