THEMES = {"default": {"ok": "#56d364", "bad": "#ff7b72", "warn": "#e3b341", "blue": "#79c0ff", "dim": "#6e7a87", "accent": "#21cfac",
                       "bg": "#0d1117", "fg": "#d1d9e0", "line": "#30363d", "raised": "#161b22", "title": "#21cfac",
                       "pick": "#1f6feb40", "pick-focus": "#1f6feb66", "veil": "#01040980"},
          "lcars": {"ok": "#99cc66", "bad": "#ff6666", "warn": "#ffcc66", "blue": "#99ccff", "dim": "#9999cc", "accent": "#ff9900",
                    "bg": "#000000", "fg": "#ffcc99", "line": "#cc99cc", "raised": "#1a1426", "title": "#000000",
                    "pick": "#ff990033", "pick-focus": "#ff990059", "veil": "#000000c0"}}
COLORS = dict(THEMES["default"])
# use_theme rebinds this name, so read it as theme.current: a from-import would keep "default".
current = "default"


def use_theme(name):
    global current
    current = name
    COLORS.update(THEMES[name])
