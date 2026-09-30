"""Busca que camaras hay disponibles y con que indice.

En Windows el indice 0 no siempre es la webcam fisica: camaras virtuales
de OBS, Teams, Nvidia Broadcast o iriun suelen ocupar los primeros
lugares. Este script prueba los indices uno por uno y muestra cual
entrega imagen real, para que no pierdas tiempo adivinando.

Uso:
    python buscar_camaras.py
    python buscar_camaras.py --hasta 8 --guardar
"""

from __future__ import annotations
import argparse
import sys

import cv2

from vision_qr.captura import backend_por_defecto, _BACKENDS


def probar(indice: int, backend: int, guardar: bool) -> dict | None:
    cap = cv2.VideoCapture(indice, backend)
    if not cap.isOpened():
        cap.release()
        return None

    ok, cuadro = cap.read()
    info = None
    if ok and cuadro is not None:
        alto, ancho = cuadro.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        info = {"indice": indice, "ancho": ancho, "alto": alto, "fps": fps}
        if guardar:
            nombre = f"camara_{indice}.png"
            cv2.imwrite(nombre, cuadro)
            info["muestra"] = nombre
    cap.release()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hasta", type=int, default=5, help="Cuantos indices probar")
    ap.add_argument("--backend", default=None,
                    help=f"Forzar backend. Opciones: {list(_BACKENDS)}")
    ap.add_argument("--guardar", action="store_true",
                    help="Guardar una imagen de cada camara encontrada")
    args = ap.parse_args()

    if args.backend:
        backend = _BACKENDS[args.backend.lower()]
        etiqueta = args.backend
    else:
        backend = backend_por_defecto()
        etiqueta = "dshow (Windows)" if sys.platform.startswith("win") else "automatico"

    print(f"Backend: {etiqueta}")
    print(f"Probando indices 0 a {args.hasta - 1}...\n")

    # Silenciar los avisos de OpenCV al abrir indices que no existen:
    # son ruido esperado, no errores.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass

    encontradas = []
    for i in range(args.hasta):
        info = probar(i, backend, args.guardar)
        if info:
            encontradas.append(info)
            extra = f"  -> {info['muestra']}" if "muestra" in info else ""
            print(f"  indice {i}:  {info['ancho']}x{info['alto']}  "
                  f"{info['fps']:.0f} fps{extra}")
        else:
            print(f"  indice {i}:  sin camara")

    print()
    if not encontradas:
        print("No se encontro ninguna camara.")
        print("En Windows revisa: Configuracion > Privacidad y seguridad > Camara,")
        print("y activa 'Permitir que las aplicaciones de escritorio accedan a la camara'.")
        print("Tambien cerra Teams, Zoom u OBS si estan tomando la camara.")
        return 1

    elegido = encontradas[0]["indice"]
    print(f"Se encontraron {len(encontradas)} camara(s).")
    if args.guardar:
        print("Abri las imagenes camara_N.png para ver cual es la que queres usar.")
    print(f"\nPone esto en config.json:")
    print(f'  "captura": {{ "tipo": "webcam", "indice": {elegido}, '
          f'"ancho": 640, "alto": 480 }}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
