"""Vista en vivo por navegador, para una Raspberry Pi sin pantalla.

La Pi corre el modulo completo y, a la vez, publica el mismo cuadro que esta
procesando, con los QR marcados y el estado (fps, mision, proxima parada).
Se mira desde otra maquina abriendo http://<ip de la Pi>:<puerto>/.

Por que existe: la camara no se puede compartir entre dos procesos, asi que
"ver la camara" y "correr el modulo" eran excluyentes. Aca el modulo mismo
entrega la imagen, sin abrir la camara dos veces.

Cuida la CPU de la Pi 3, que es el recurso escaso:
  - no dibuja ni comprime nada mientras nadie esta mirando;
  - limita a fps_max los cuadros que emite (por defecto 8);
  - comprime a JPEG calidad 70.
Solo usa la libreria estandar y OpenCV.
"""

from __future__ import annotations
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import cv2

LIMITE = b"cuadro"


class VistaWeb:
    def __init__(self, puerto: int = 8080, fps_max: float = 8.0, calidad: int = 70):
        self.puerto = puerto
        self.calidad = calidad
        self._min_intervalo = 1.0 / fps_max if fps_max > 0 else 0.0
        self._ultimo_envio = 0.0
        self._jpg: Optional[bytes] = None
        self._numero = 0
        self._cond = threading.Condition()
        self._clientes = 0
        self._activo = True
        self._servidor = ThreadingHTTPServer(("0.0.0.0", puerto), self._manejador())
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._hilo.start()

    # --- lo que usa el bucle principal -------------------------------------

    def quiere_cuadro(self) -> bool:
        """True si alguien mira y ya toca emitir otro cuadro. Es barato."""
        if self._clientes <= 0:
            return False
        return (time.monotonic() - self._ultimo_envio) >= self._min_intervalo

    def publicar(self, cuadro) -> None:
        ok, buf = cv2.imencode(".jpg", cuadro, [cv2.IMWRITE_JPEG_QUALITY, self.calidad])
        if not ok:
            return
        self._ultimo_envio = time.monotonic()
        with self._cond:
            self._jpg = buf.tobytes()
            self._numero += 1
            self._cond.notify_all()

    def cerrar(self) -> None:
        self._activo = False
        with self._cond:
            self._cond.notify_all()
        self._servidor.shutdown()
        self._servidor.server_close()

    def url(self) -> str:
        return f"http://{_ip_local()}:{self.puerto}/"

    # --- HTTP ----------------------------------------------------------------

    def _manejador(self):
        vista = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    cuerpo = (b"<html><body style='margin:0;background:#111'>"
                              b"<img src='/video' style='max-width:100%'></body></html>")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(cuerpo)))
                    self.end_headers()
                    self.wfile.write(cuerpo)
                elif self.path == "/video":
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     f"multipart/x-mixed-replace; boundary={LIMITE.decode()}")
                    self.end_headers()
                    vista._clientes += 1
                    visto = 0
                    try:
                        while vista._activo:
                            with vista._cond:
                                if not vista._cond.wait_for(
                                        lambda: vista._numero != visto or not vista._activo,
                                        timeout=2.0):
                                    continue
                                if not vista._activo:
                                    break
                                visto, jpg = vista._numero, vista._jpg
                            self.wfile.write(
                                b"--" + LIMITE + b"\r\nContent-Type: image/jpeg\r\n"
                                + f"Content-Length: {len(jpg)}\r\n\r\n".encode() + jpg + b"\r\n")
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    finally:
                        vista._clientes -= 1
                else:
                    self.send_error(404)
        return H


def _ip_local() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
