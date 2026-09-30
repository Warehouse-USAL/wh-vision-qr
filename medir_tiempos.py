"""Mide, con la camara en vivo, en que se va el tiempo de cada cuadro.

Para cuando los fps del programa no son los que se esperaban. Separa lo que
cuesta leer la camara, pasar a gris y decodificar con ZBar, sobre cuadros
reales. Es mas fiel que benchmark.py, que usa una escena sintetica o una foto
suelta: en una prueba real ZBar tardo 88 ms sobre la escena en vivo y 44 ms
sobre la foto que guarda buscar_camaras.py (el primer cuadro, que sale oscuro).

Uso (la camara tiene que estar libre):
    python medir_tiempos.py
    python medir_tiempos.py --ancho 320 --alto 240
    python medir_tiempos.py --segundos 20 --indice 1

Mostrale etiquetas a la camara mientras corre, como en uso normal.
"""

from __future__ import annotations
import argparse
import statistics as st
import sys
import time

import cv2

from vision_qr.captura import backend_por_defecto, _BACKENDS


def main() -> int:
    ap = argparse.ArgumentParser(description="Tiempos por cuadro con camara en vivo")
    ap.add_argument("--indice", type=int, default=0)
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--fourcc", default="MJPG")
    ap.add_argument("--backend", default=None, help=f"Opciones: {list(_BACKENDS)}")
    ap.add_argument("--segundos", type=float, default=10.0)
    args = ap.parse_args()

    try:
        from pyzbar.pyzbar import decode, ZBarSymbol
    except ImportError as e:
        sys.exit(f"No se pudo cargar pyzbar/ZBar: {e}")

    backend = _BACKENDS[args.backend.lower()] if args.backend else backend_por_defecto()
    cap = cv2.VideoCapture(args.indice, backend)
    if not cap.isOpened():
        sys.exit(f"No se pudo abrir la camara {args.indice}. Probar buscar_camaras.py")
    if args.fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.alto)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    for _ in range(15):        # dejar que se estabilice la exposicion
        cap.read()
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camara: {ancho}x{alto}. Midiendo {args.segundos:.0f} s, mostrale etiquetas...")

    leer, gris, zbar, con_qr = [], [], [], 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < args.segundos:
        a = time.perf_counter()
        ok, cuadro = cap.read()
        if not ok:
            continue
        b = time.perf_counter()
        g = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
        c = time.perf_counter()
        lecturas = decode(g, symbols=[ZBarSymbol.QRCODE])
        d = time.perf_counter()
        leer.append((b - a) * 1000)
        gris.append((c - b) * 1000)
        zbar.append((d - c) * 1000)
        con_qr += bool(lecturas)
    cap.release()

    n = len(leer)
    if n == 0:
        sys.exit("La camara no entrego cuadros.")
    total = st.median(leer) + st.median(gris) + st.median(zbar)
    print(f"cuadros: {n}  ({n / args.segundos:.1f} fps)   con QR: {con_qr}")
    print(f"cap.read()   mediana {st.median(leer):6.1f} ms   maximo {max(leer):6.1f}")
    print(f"a gris       mediana {st.median(gris):6.1f} ms")
    print(f"ZBar         mediana {st.median(zbar):6.1f} ms   maximo {max(zbar):6.1f}")
    print(f"por cuadro   {total:6.1f} ms  ->  techo de unos {1000 / total:.1f} fps "
          f"(la camara no pasa de {args.fps})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
