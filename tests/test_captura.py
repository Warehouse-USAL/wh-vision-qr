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


# --- FuenteRed: lee el flujo MJPEG de transmitir_camara.py --------------------

def _servidor_mjpeg(cuadros):
    """Emite los cuadros dados en multipart, como transmitir_camara.py."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    jpgs = [cv2.imencode(".jpg", c)[1].tobytes() for c in cuadros]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=cuadro")
            self.end_headers()
            try:
                for _ in range(200):  # repite: la fuente se queda con el ultimo
                    for j in jpgs:
                        self.wfile.write(b"--cuadro\r\nContent-Type: image/jpeg\r\n"
                                         + f"Content-Length: {len(j)}\r\n\r\n".encode() + j + b"\r\n")
                        self.wfile.flush()
                    import time
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError):
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_fuente_red_recibe_cuadros_del_flujo():
    from vision_qr.captura import FuenteRed
    cuadro = np.full((120, 160, 3), 200, np.uint8)
    srv = _servidor_mjpeg([cuadro])
    try:
        with FuenteRed(f"http://127.0.0.1:{srv.server_port}/video") as f:
            recibido = next(f.cuadros())
        assert recibido.shape == (120, 160, 3)
    finally:
        srv.shutdown()
        srv.server_close()


def test_fuente_red_se_construye_desde_la_configuracion():
    from vision_qr.captura import FuenteRed
    f = construir_fuente({"tipo": "red", "url": "http://10.0.0.5:8080/video"})
    assert isinstance(f, FuenteRed) and f.url.endswith("/video")


def test_fuente_red_sin_servidor_no_mata_el_proceso():
    """RF-07: si la laptop no esta, reintenta en silencio y guarda el motivo."""
    import time
    from vision_qr.captura import FuenteRed
    f = FuenteRed("http://127.0.0.1:9/video", reintento=0.1, timeout=0.5)
    gen = f.cuadros()
    import threading
    threading.Thread(target=lambda: next(gen, None), daemon=True).start()
    time.sleep(1.0)
    f.cerrar()
    assert f.error is not None
