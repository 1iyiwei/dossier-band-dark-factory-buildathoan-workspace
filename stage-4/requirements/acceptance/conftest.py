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


# ------------------------------------------------------------------ browser (stage 2 UI tests)
@pytest.fixture(scope="session")
def pw_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    sync_api.expect.set_options(timeout=10_000)
    pw = sync_api.sync_playwright().start()
    browser = pw.chromium.launch()
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture()
def new_page(pw_browser):
    """Factory: a page in a fresh browser context (own storage) at the given viewport."""
    from ui_lib import VIEWPORTS
    made = []

    def make(viewport="desktop"):
        ctx = pw_browser.new_context(viewport=VIEWPORTS[viewport] if isinstance(viewport, str)
                                     else viewport, locale="en-US", timezone_id="UTC")
        ctx.set_default_timeout(10_000)
        made.append(ctx)
        return ctx.new_page()

    yield make
    for ctx in made:
        ctx.close()


@pytest.fixture()
def page(new_page):
    return new_page("desktop")
