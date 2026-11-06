import pytest

import nyx.launch
import nyx.remind
import nyx.vol

# Módulos cuya main() corta por sys.platform == "win32" antes de nada.
# sys es un singleton: parchearlo por cualquiera de ellos lo parchea para todos.
_MODULOS_PLATAFORMA = (nyx.launch, nyx.remind, nyx.vol)


@pytest.fixture(autouse=True)
def _log_aislado(tmp_path, monkeypatch):
    """Los tests no escriben en el log real de jerga (~/.local/state/jerga/jerga.log)."""
    import nyx.config as cfg

    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cfg, "LOG_PATH", tmp_path / "state" / "jerga.log")
    monkeypatch.setattr(cfg, "_log_file", None)


@pytest.fixture(autouse=True)
def _plataforma_linux(monkeypatch):
    """La suite corre como en Linux por defecto; el test del stub win32 se pone a win32 él mismo
    (corre después, así que su setattr gana). Sin diccionario de nombres de módulo: pytest importa
    test_launch sin el prefijo tests. y el lookup fallaba silenciosamente en Windows."""
    for mod in _MODULOS_PLATAFORMA:
        monkeypatch.setattr(mod.sys, "platform", "linux")
