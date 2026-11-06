import pytest

import jerga.launch
import jerga.remind
import jerga.vol

# Módulos cuya main() corta por sys.platform == "win32" antes de nada
_MODULOS_PLATAFORMA = {
    "tests.test_launch": jerga.launch,
    "tests.test_vol": jerga.vol,
    "tests.test_remind": jerga.remind,
}


@pytest.fixture(autouse=True)
def _log_aislado(tmp_path, monkeypatch):
    """Los tests no escriben en el log real de jerga (~/.local/state/jerga/jerga.log)."""
    import jerga.config as cfg

    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cfg, "LOG_PATH", tmp_path / "state" / "jerga.log")
    monkeypatch.setattr(cfg, "_log_file", None)


@pytest.fixture(autouse=True)
def _plataforma_linux(monkeypatch, request):
    """La suite corre como en Linux por defecto; el test del stub win32 se pone a win32 él mismo
    (corre después, así que su setattr gana). Solo toca el módulo bajo test."""
    mod = _MODULOS_PLATAFORMA.get(request.module.__name__)
    if mod is not None:
        monkeypatch.setattr(mod.sys, "platform", "linux")
