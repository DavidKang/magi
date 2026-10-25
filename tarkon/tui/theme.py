THEMES = {"default": {"ok": "#56d364", "bad": "#ff7b72", "warn": "#e3b341", "blue": "#79c0ff", "dim": "#6e7a87", "accent": "#21cfac",
                       "focus": "#21cfac", "bg": "#0d1117", "fg": "#d1d9e0", "line": "#30363d", "raised": "#161b22", "title": "#21cfac",
                       "pick": "#1f6feb40", "pick-focus": "#1f6feb66", "veil": "#01040980"},
          # LCARS palettes from thelcars.com; okuda is its Classic set (TNG and DS9).
          "okuda": {"ok": "#99cc66", "bad": "#cf4f4f", "warn": "#edb378", "blue": "#8899ff", "dim": "#8a72a7", "accent": "#eb943a",
                    "focus": "#eb943a", "bg": "#000000", "fg": "#fcc19f", "line": "#c082a9", "raised": "#1a1426", "title": "#000000",
                    "pick": "#eb943a33", "pick-focus": "#eb943a59", "veil": "#000000c0"},
          "picard": {"ok": "#99cc66", "bad": "#e7442a", "warn": "#ff977b", "blue": "#41c4f7", "dim": "#6d748c", "accent": "#37a6d1",
                     "focus": "#37a6d1", "bg": "#000000", "fg": "#d2d5df", "line": "#9ea5ba", "raised": "#2f3749", "title": "#000000",
                     "pick": "#37a6d133", "pick-focus": "#37a6d159", "veil": "#000000c0"},
          # NERV's screens, in nerv-ui's design tokens (github.com/mdrbx/nerv-ui): Evangelion has no official palette.
          # nerv-ui has no grey for dimmed text (its #333333 is for borders), so dim is a mid grey that reads on black.
          "nerv": {"ok": "#00ff00", "bad": "#ff0000", "warn": "#ffaa00", "blue": "#00ffff", "dim": "#808080", "accent": "#ff9900",
                   "focus": "#ff9900", "bg": "#000000", "fg": "#ff9900", "line": "#00ff00", "raised": "#1a1a1a", "title": "#000000",
                   "pick": "#ff990033", "pick-focus": "#ff990059", "veil": "#000000c0"},
          # Unit-01 in nerv-ui's tokens: purple armour (--color-nerv-purple), LCD green trim, nerv white text.
          "eva01": {"ok": "#39ff14", "bad": "#ff0000", "warn": "#ff9900", "blue": "#00ffff", "dim": "#808080", "accent": "#39ff14",
                    "focus": "#39ff14", "bg": "#000000", "fg": "#e0e0e0", "line": "#9933ff", "raised": "#1f0d33", "title": "#000000",
                    "pick": "#9933ff33", "pick-focus": "#9933ff59", "veil": "#000000c0"}}
LCARS = ["okuda", "picard"]
# The themes that draw their own frame instead of the default layout.
FRAMES = {**{name: "lcars" for name in LCARS}, "nerv": "nerv", "eva01": "nerv"}
# Themes no longer offered, read as the closest one still offered so an old config still starts.
DROPPED = {"lcars": "okuda", "voyager": "okuda", "magi": "nerv"}
COLORS = dict(THEMES["default"])
# use_theme rebinds this name, so read it as theme.current: a from-import would keep "default".
current = "default"


def frame():
    return FRAMES.get(current)


def lcars():
    return frame() == "lcars"


def offered(name):
    name = DROPPED.get(name, name)
    return name if name in THEMES else "default"


def use_theme(name):
    global current
    COLORS.update(THEMES[name])
    current = name
