import pytest

from fastvideoassembly import app


@pytest.fixture(autouse=True)
def isolated_launch(request, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "user_config_path", lambda *args, **kwargs: tmp_path)
    initialize = app.Application.__init__

    def initialize_test(self, *args, **kwargs):
        kwargs.setdefault("no_profile", request.node.get_closest_marker("profile") is None)
        kwargs.setdefault("minimize", True)
        initialize(self, *args, **kwargs)

    monkeypatch.setattr(app.Application, "__init__", initialize_test)
