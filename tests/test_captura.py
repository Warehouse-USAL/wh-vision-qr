import cv2
import numpy as np
import pytest

from vision_qr.captura import FuenteArchivos, FuenteVideo, construir_fuente


@pytest.fixture
def clip_1080p(tmp_path):
    """Clip 16:9 de 5 cuadros, como el que graba una GoPro."""
    ruta = tmp_path / "clip.mp4"
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1920, 1080))
    for i in range(5):
        w.write(np.full((1080, 1920, 3), 40 * i, np.uint8))
    w.release()
    return str(ruta)


def test_video_sin_reducir_conserva_la_resolucion(clip_1080p):
    cuadros = list(FuenteVideo(clip_1080p, velocidad=0).cuadros())
    assert len(cuadros) == 5
    assert cuadros[0].shape[:2] == (1080, 1920)


def test_reducir_por_ancho_conserva_la_proporcion(clip_1080p):
    """Estirar 16:9 a 4:3 deformaria los cuadrados del QR y falsearia la prueba."""
    cuadro = next(FuenteVideo(clip_1080p, velocidad=0, ancho=640).cuadros())
    assert cuadro.shape[:2] == (360, 640)


def test_reducir_con_ancho_y_alto_los_respeta(clip_1080p):
    cuadro = next(FuenteVideo(clip_1080p, velocidad=0, ancho=640, alto=480).cuadros())
    assert cuadro.shape[:2] == (480, 640)


def test_saltar_procesa_uno_de_cada_n(clip_1080p):
    assert len(list(FuenteVideo(clip_1080p, velocidad=0, saltar=1).cuadros())) == 3


def test_video_inexistente_da_un_error_claro():
    with pytest.raises(RuntimeError, match="No se pudo abrir el video"):
        list(FuenteVideo("no_existe.mp4").cuadros())


def test_archivos_sin_coincidencias_da_un_error_claro(tmp_path):
    with pytest.raises(RuntimeError, match="No hay imagenes"):
        list(FuenteArchivos(str(tmp_path / "*.png")).cuadros())


def test_la_fabrica_pasa_los_parametros_de_video():
    f = construir_fuente({"tipo": "video", "ruta": "x.mp4", "ancho": 640, "saltar": 2})
    assert (f.ancho, f.alto, f.saltar) == (640, None, 2)


def test_la_fabrica_pasa_el_codec_de_la_camara():
    f = construir_fuente({"tipo": "webcam", "fourcc": "MJPG", "backend": "v4l2"})
    assert f.fourcc == "MJPG"


def test_fuente_desconocida():
    with pytest.raises(ValueError):
        construir_fuente({"tipo": "telepatia"})
