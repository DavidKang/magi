import tomllib

from builders import ROOT


def test_every_subpackage_ships():
    declared = set(tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["packages"])
    found = {".".join(init.parent.relative_to(ROOT).parts) for init in (ROOT / "magi").rglob("__init__.py")}
    assert found == declared
