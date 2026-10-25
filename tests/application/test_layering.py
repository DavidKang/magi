from builders import ROOT, imported, outside

APPLICATION = ROOT / "magi" / "application"
STDLIB = {"concurrent", "dataclasses", "math", "typing"}


def test_application_reaches_adapters_only_through_ports():
    modules = sorted(APPLICATION.glob("*.py"))
    assert modules, "the use case lives in magi/application"
    for path in modules:
        reached = outside(imported(path, "magi.application"), STDLIB, ["magi.application", "magi.domain"])
        assert reached == [], f"{path.name} imports more than the domain and its ports: {reached}"
