import cv2
import numpy as np
import pytest

# Si ZBar no esta instalado en la maquina, estos tests se saltean en vez de
# fallar: no es un bug del codigo, es un requisito del sistema.
pytest.importorskip("pyzbar.pyzbar")
qrcode = pytest.importorskip("qrcode")

from vision_qr.decodificador import Decodificador
from vision_qr.payload import construir


def imagen_qr(texto, lado=300):
    q = qrcode.QRCode(box_size=10, border=4)
    q.add_data(texto)
    q.make(fit=True)
    img = np.array(q.make_image().convert("RGB"))
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return cv2.resize(img, (lado, lado), interpolation=cv2.INTER_NEAREST)


def test_lee_una_etiqueta_con_sus_cuatro_esquinas():
    lecturas = Decodificador(usar_respaldo=False).leer(imagen_qr(construir("PA1")))
    assert [l.contenido for l in lecturas] == ["WH2|PA1"]
    assert len(lecturas[0].esquinas) == 4
    assert lecturas[0].motor == "zbar"
    assert lecturas[0].lado_aparente > 0


def test_cuadro_vacio_no_devuelve_nada():
    vacio = np.full((480, 640, 3), 200, np.uint8)
    assert Decodificador(usar_respaldo=False).leer(vacio) == []


def test_lee_dos_codigos_en_el_mismo_cuadro():
    a, b = imagen_qr("WH2|PA1", 200), imagen_qr("WH2|PM3", 200)
    cuadro = np.full((300, 600, 3), 255, np.uint8)
    cuadro[50:250, 20:220] = a
    cuadro[50:250, 350:550] = b
    leidos = {l.contenido for l in Decodificador(usar_respaldo=False).leer(cuadro)}
    assert leidos == {"WH2|PA1", "WH2|PM3"}


def test_tambien_lee_codigos_ajenos_el_filtro_es_de_otra_capa():
    """El decodificador lee todo; descartar lo ajeno es trabajo de payload."""
    lecturas = Decodificador(usar_respaldo=False).leer(imagen_qr("https://ejemplo.org"))
    assert lecturas and lecturas[0].contenido == "https://ejemplo.org"


def test_lee_con_rotacion_y_poca_luz():
    """Las condiciones por las que se eligio ZBar sobre el detector de OpenCV."""
    base = imagen_qr(construir("PA2"))
    h, w = base.shape[:2]
    girada = cv2.warpAffine(base, cv2.getRotationMatrix2D((w / 2, h / 2), 45, 1.0),
                            (w, h), borderValue=(255, 255, 255))
    oscura = np.clip(girada.astype(np.float32) * 0.35 + 20, 0, 255).astype(np.uint8)
    assert Decodificador(usar_respaldo=False).leer(oscura)[0].contenido == "WH2|PA2"
