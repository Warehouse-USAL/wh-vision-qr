"""Interpretacion del estado de energia de la Raspberry Pi.

Existe por un caso real: una Pi 3 registra una subtension un instante al
arrancar (0x50000) y el benchmark marcaba como afectada una medicion limpia,
porque esos avisos no se borran hasta reiniciar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark import _leer_estado, evaluar_energia  # noqa: E402


def test_sin_avisos():
    assert evaluar_energia(0x0, 0x0) == ("ok", [])


def test_avisos_del_arranque_no_afectan_la_medicion():
    """Regresion: 0x50000 antes y despues es el caso tipico de la Pi 3."""
    veredicto, causas = evaluar_energia(0x50000, 0x50000)
    assert veredicto == "previo"
    assert all("antes de medir" in c for c in causas)


def test_subtension_nueva_durante_la_medicion_si_afecta():
    veredicto, causas = evaluar_energia(0x0, 0x50000)
    assert veredicto == "afectado"
    assert any("subtension durante la medicion" in c for c in causas)


def test_un_aviso_nuevo_se_detecta_aunque_ya_hubiera_otros():
    veredicto, causas = evaluar_energia(0x10000, 0x90000)  # se suma limite de temperatura
    assert veredicto == "afectado"
    assert any("temperatura" in c for c in causas)


def test_un_problema_que_sigue_ahora_siempre_afecta():
    veredicto, causas = evaluar_energia(0x1, 0x10001)
    assert veredicto == "afectado"
    assert "subtension AHORA" in causas


def test_leer_estado():
    assert _leer_estado("throttled=0x50000") == 0x50000
    assert _leer_estado("throttled=0x0") == 0
    assert _leer_estado(None) is None
    assert _leer_estado("basura") is None
