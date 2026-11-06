import pytest


@pytest.fixture(autouse=True)
def _log_aislado(tmp_path, monkeypatch):
    """Los tests no escriben en el log real de jerga (~/.local/state/jerga/jerga.log)."""
    import jerga.config as cfg

    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cfg, "LOG_PATH", tmp_path / "state" / "jerga.log")
    monkeypatch.setattr(cfg, "_log_file", None)
