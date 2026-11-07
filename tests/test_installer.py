"""Tarea 3 del plan 003: instaladores y unidad systemd — se comprueban leyendo el fuente
(el script no se ejecuta aquí: lo instala la CI de install.yml en contenedores limpios)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _sh() -> str:
    return (RAIZ / "install.sh").read_text(encoding="utf-8")


def _ps1() -> str:
    return (RAIZ / "install.ps1").read_text(encoding="utf-8")


def _yml() -> str:
    return (RAIZ / ".github/workflows/install.yml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ unidad
def test_unidad_systemd_es_nyx():
    sh = _sh()
    assert 'UNIT="$HOME/.config/systemd/user/nyx.service"' in sh
    unit = re.search(r'cat > "\$UNIT" <<EOF\n(.*?)\nEOF', sh, re.S).group(1)
    assert "Description=nyx" in unit
    assert "venv/bin/nyx" in unit  # ExecStart
    assert "jerga" not in unit
    assert "systemctl --user enable nyx.service" in sh
    assert "systemctl --user restart nyx.service" in sh


def test_el_servicio_viejo_se_retira_sin_borrarse():
    sh = _sh()
    # lo detecta (aunque solo esté cargada, sin fichero propio)…
    assert "systemctl --user cat jerga.service" in sh
    # …lo para y desactiva…
    assert "systemctl --user disable --now jerga.service" in sh
    # …y dice cómo purgarlo a mano…
    assert "rm ~/.config/systemd/user/jerga.service && systemctl --user daemon-reload" in sh
    # …pero no lo borra él mismo
    assert 'rm -f "$VIEJA_UNIT"' not in sh


def test_venv_bin():
    sh = _sh()
    # venv en ~/.local/share/nyx (NYX_HOME manda; JERGA_HOME histórico cae como fallback)
    assert 'PREFIX="${NYX_HOME:-${JERGA_HOME:-$HOME/.local/share/nyx}}"' in sh
    assert 'ln -sf "$PREFIX/venv/bin/nyx" "$BIN/nyx"' in sh


def test_urls_del_repo_son_kcurtet_nyx():
    for texto in (_sh(), _ps1(), (RAIZ / "pyproject.toml").read_text(encoding="utf-8")):
        assert "kcurtet/nyx" in texto
        assert "kcurtet/jerga" not in texto


def test_windows_instala_el_paquete_nyx():
    ps1 = _ps1()
    assert '"nyx$extra @ git+$Repo"' in ps1  # instala el paquete nyx
    assert '"nyx-gui.exe"' in ps1  # arranque automático


def test_windows_retira_el_uv_tool_viejo_de_jerga():
    """Review 003: en upgrade, el jerga.exe del uv tool viejo gana a jerga.cmd por PATHEXT
    (el usuario seguiría en el binario viejo sin aviso): se desinstala (tolerante al fallo)
    y se retira el jerga.lnk del Startup — al instalar y también en -Uninstall."""
    ps1 = _ps1()
    assert ps1.count("uv tool uninstall jerga 2>$null") == 2
    assert ps1.count('"jerga.lnk"') == 2  # el atajo de arranque viejo, fuera en ambos caminos


def test_la_regla_udev_vieja_se_retira_siempre():
    """Review 003: el rm de la regla jerga estaba DENTRO del guard «no existe la nueva» →
    en reinstalación la vieja sobrevivía para siempre."""
    sh = _sh()
    guard = sh.index("if [ ! -f /etc/udev/rules.d/80-nyx-uinput.rules ]; then")
    fi = sh.index("\n  fi", guard)  # el fi que cierra ese guard
    assert sh.index("rm -f /etc/udev/rules.d/80-jerga-uinput.rules", guard) > fi


def test_el_mensaje_final_dice_nyx_no_trinity():
    """Review 003: la wake «Trinity» murió con el renombrado; el mensaje final dice «Nyx, …»."""
    sh = _sh()
    assert "«Nyx, …»" in sh
    assert "«Trinity" not in sh


def test_ci_de_instalacion_comprueba_nyx():
    yml = _yml()
    assert '"nyx/**"' in yml and '"jerga/**"' not in yml  # dispara con cambios en el paquete nyx
    assert '"$HOME/.local/bin/nyx" --version' in yml
    assert '"$HOME/.local/share/nyx/venv/bin/python"' in yml


@pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash (Windows)")
def test_install_sh_parsea():
    subprocess.run(["bash", "-n", str(RAIZ / "install.sh")], check=True)
