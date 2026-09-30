"""Emite la camara de la laptop por la red, para que la Raspberry Pi la lea.

Es un puente de DEMOSTRACION: la laptop captura y comprime a JPEG, la Pi lo
recibe y corre el modulo completo encima. Sirve para ver el flujo en vivo
mientras no hay camara USB en la Pi.

No mide el rendimiento de la camara definitiva: los fps incluyen la compresion
y la red. Para medir la camara real: probar_camara.py en la Pi con la USB.

Uso, en la LAPTOP:
    python transmitir_camara.py                    # camara 0, puerto 8080
    python transmitir_camara.py --indice 1 --ancho 640 --alto 480
    python transmitir_camara.py --video clips/vuelta_2.mp4   # sin camara, repite un clip

Despues, en la Pi:
    python -m vision_qr.main --config config.pi-red.json

Si el navegador de la laptop abre http://localhost:8080/ se ve lo mismo que
recibe la Pi. En Windows, la primera vez el firewall pregunta: permitir en
"redes privadas".
"""

from __future__ import annotations
import argparse
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from vision_qr.captura import backend_por_defecto, _BACKENDS

LIMITE = b"cuadro"


class Emisor:
    """Captura en un hilo y deja el ultimo JPEG disponible para los clientes."""

    def __init__(self, args):
        self.args = args
        self.jpg = None
        self.numero = 0
        self.cond = threading.Condition()
        self.activo = True

    def _abrir(self):
        a = self.args
        if a.video:
            cap = cv2.VideoCapture(a.video)
        else:
            backend = _BACKENDS[a.backend.lower()] if a.backend else backend_por_defecto()
            cap = cv2.VideoCapture(a.indice, backend)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.ancho)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.alto)
            cap.set(cv2.CAP_PROP_FPS, a.fps)
        return cap

    def correr(self):
        cap = self._abrir()
        if not cap.isOpened():
            self.activo = False
            raise RuntimeError("No se pudo abrir la camara (o el video). Probar buscar_camaras.py")
        pausa = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or self.args.fps) if self.args.video else 0.0
        while self.activo:
            t0 = time.monotonic()
            ok, cuadro = cap.read()
            if not ok:
                if self.args.video:          # un clip se repite sin parar
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.2)
                continue
            ok, buf = cv2.imencode(".jpg", cuadro, [cv2.IMWRITE_JPEG_QUALITY, self.args.calidad])
            if ok:
                with self.cond:
                    self.jpg = buf.tobytes()
                    self.numero += 1
                    self.cond.notify_all()
            resto = pausa - (time.monotonic() - t0)
            if resto > 0:
                time.sleep(resto)
        cap.release()


def _manejador(emisor: Emisor):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sin ruido por cada peticion
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                cuerpo = b"<html><body style='margin:0;background:#111'><img src='/video' style='max-width:100%'></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
            elif self.path == "/foto":
                with emisor.cond:
                    jpg = emisor.jpg
                if jpg is None:
                    self.send_error(503, "todavia sin cuadros")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpg)))
                self.end_headers()
                self.wfile.write(jpg)
            elif self.path == "/video":
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={LIMITE.decode()}")
                self.end_headers()
                visto = 0
                try:
                    while emisor.activo:
                        with emisor.cond:
                            if not emisor.cond.wait_for(lambda: emisor.numero != visto, timeout=2.0):
                                continue
                            visto, jpg = emisor.numero, emisor.jpg
                        self.wfile.write(b"--" + LIMITE + b"\r\nContent-Type: image/jpeg\r\n"
                                         + f"Content-Length: {len(jpg)}\r\n\r\n".encode() + jpg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            else:
                self.send_error(404)
    return H


def _ip_local() -> str:
    """La IP con la que esta maquina sale a la red (no envia nada)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Emisor de camara por red - Warehouse USAL")
    ap.add_argument("--indice", type=int, default=0)
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--backend", default=None, help=f"Opciones: {list(_BACKENDS)}")
    ap.add_argument("--calidad", type=int, default=80, help="Calidad JPEG 1-100")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--video", default=None, help="Emitir un clip en bucle en vez de la camara")
    args = ap.parse_args()

    emisor = Emisor(args)
    hilo = threading.Thread(target=emisor.correr, daemon=True)
    hilo.start()
    time.sleep(0.5)
    if not emisor.activo:
        print("No se pudo abrir la camara (o el video). Probar: python buscar_camaras.py")
        return 1

    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), _manejador(emisor))
    ip = _ip_local()
    print(f"Emitiendo {'el clip ' + args.video if args.video else 'la camara ' + str(args.indice)}"
          f" a {args.ancho}x{args.alto}, JPEG calidad {args.calidad}")
    print(f"  Verlo aca   : http://localhost:{args.puerto}/")
    print(f"  URL para la Pi: http://{ip}:{args.puerto}/video")
    print("Ctrl+C para cortar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        emisor.activo = False
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
