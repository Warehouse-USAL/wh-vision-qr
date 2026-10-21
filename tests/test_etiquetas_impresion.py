import sys
from pathlib import Path

import pytest

pytest.importorskip("qrcode")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generar_etiquetas  # noqa: E402


def test_dos_copias_por_riel_y_home_una_vez(tmp_path):
    # 7 paradas del circuito x 2 + P1 + P2
    assert generar_etiquetas.hoja_impresion(tmp_path, 70, 2) == 16
    assert (tmp_path / "hoja_impresion.pdf").stat().st_size > 0
    assert (tmp_path / "hoja_impresion_1.png").exists()


def test_una_copia(tmp_path):
    assert generar_etiquetas.hoja_impresion(tmp_path, 70, 1) == 9


def test_el_codigo_mide_lo_pedido_y_la_imagen_es_mayor():
    lado = generar_etiquetas.lado_imagen_para_codigo(70)
    assert 70 < lado < 110


def test_copias_invalidas(tmp_path):
    with pytest.raises(ValueError):
        generar_etiquetas.hoja_impresion(tmp_path, 70, 3)
