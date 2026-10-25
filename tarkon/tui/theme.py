THEMES = {"default": {"ok": "#56d364", "bad": "#ff7b72", "warn": "#e3b341", "blue": "#79c0ff", "dim": "#6e7a87", "accent": "#21cfac",
                       "bg": "#0d1117", "fg": "#d1d9e0", "line": "#30363d", "raised": "#161b22", "title": "#21cfac",
                       "pick": "#1f6feb40", "pick-focus": "#1f6feb66", "veil": "#01040980"},
          # LCARS palettes from thelcars.com; okuda is its Classic set (TNG and DS9).
          "okuda": {"ok": "#99cc66", "bad": "#cf4f4f", "warn": "#edb378", "blue": "#8899ff", "dim": "#8a72a7", "accent": "#eb943a",
                    "bg": "#000000", "fg": "#fcc19f", "line": "#c082a9", "raised": "#1a1426", "title": "#000000",
                    "pick": "#eb943a33", "pick-focus": "#eb943a59", "veil": "#000000c0"},
          "picard": {"ok": "#99cc66", "bad": "#e7442a", "warn": "#ff977b", "blue": "#41c4f7", "dim": "#6d748c", "accent": "#37a6d1",
                     "bg": "#000000", "fg": "#d2d5df", "line": "#9ea5ba", "raised": "#2f3749", "title": "#000000",
                     "pick": "#37a6d133", "pick-focus": "#37a6d159", "veil": "#000000c0"}}
LCARS = ["okuda", "picard"]
COLORS = dict(THEMES["default"])
# use_theme rebinds this name, so read it as theme.current: a from-import would keep "default".
current = "default"


def lcars():
    return current in LCARS


def use_theme(name):
    global current
    current = name
    COLORS.update(THEMES[name])
