import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ANALYST_CORPUS, Api, Mock  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "corpus: needs the mock to serve the analyst corpus")
    config.addinivalue_line("markers", "slow: takes more than ~20 s")


def pytest_collection_modifyitems(config, items):
    if ANALYST_CORPUS:
        return
    skip = pytest.mark.skip(reason="ANALYST_CORPUS=0: mock is not serving the analyst corpus")
    for it in items:
        if "corpus" in it.keywords:
            it.add_marker(skip)


@pytest.fixture(scope="session")
def api():
    return Api()


@pytest.fixture(scope="session")
def mock():
    return Mock()


@pytest.fixture()
def fresh(api, mock):
    """Clean service + clean mock (epoch 0, no faults, empty log). Returns (api, mock)."""
    api.reset()
    mock.reset(0)
    yield api, mock
    mock.reset(0)
