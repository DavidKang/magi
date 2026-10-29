import inspect

import pytest

from magi.adapters import clock, factory, github, jira, storage
from magi.application import ports


def calls(port):
    return {name: list(inspect.signature(member).parameters)[1:] for name, member in vars(port).items()
            if inspect.isfunction(member) and not name.startswith("_")}


@pytest.mark.parametrize("port, adapter", [(ports.Tickets, jira), (ports.PullRequests, github),
                                           (ports.Store, storage.JsonFiles), (ports.Clock, clock.SystemClock),
                                           (ports.FactorySource, factory)])
def test_adapters_answer_their_ports(port, adapter):
    def parameters(name):
        found = list(inspect.signature(getattr(adapter, name)).parameters)
        return found[1:] if inspect.isclass(adapter) else found
    assert {name: parameters(name) for name in calls(port)} == calls(port), \
        f"{adapter.__name__} takes the calls {port.__name__} makes, with the same parameters"
