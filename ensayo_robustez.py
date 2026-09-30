"""Ensayo de robustez del decodificador (base de QR-39).

Genera una etiqueta, la degrada de formas que imitan las condiciones
reales del warehouse y mide que sobrevive cada motor. Sirve para tres
cosas:

  1. Justificar con numeros la eleccion de ZBar frente al detector nativo.
  2. Detectar regresiones cuando alguien toque el decodificador.
  3. Saber de antemano cual es el modo de falla que hay que atacar en el
     montaje fisico.

Uso:
    python ensayo_robustez.py
    python ensayo_robustez.py --guardar casos/
"""

from __future__ import annotations
import argparse
from pathlib import Path

import cv2
import numpy as np
import qrcode
from qrcode.constants import ERROR_CORRECT_Q

from vision_qr.decodificador import Decodificador
from vision_qr.payload import construir, interpretar, PayloadInvalido


def etiqueta_base() -> np.ndarray:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=10, border=4)
    qr.add_data(construir("PA1"))
    qr.make(fit=True)
    img = np.array(qr.make_image(fill_color="black", back_color="white").convert("RGB"))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def rotar(im, ang):
    h, w = im.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(im, M, (w, h), borderValue=(255, 255, 255))


def perspectiva(im, k):
    h, w = im.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[k * w, k * h * .5], [w, 0], [w - k * w, h - k * h * .5], [0, h]])
    return cv2.warpPerspective(im, cv2.getPerspectiveTransform(src, dst), (w, h),
                               borderValue=(255, 255, 255))


def oscurecer(im, f):
    return np.clip(im.astype(np.float32) * f + 20, 0, 255).astype(np.uint8)


def desenfoque(im, k):
    return cv2.GaussianBlur(im, (k, k), 0)


def barrido(im, largo):
    """Borroneo direccional: imita el Rover avanzando durante la exposicion."""
    k = np.zeros((largo, largo))
    k[largo // 2, :] = 1
    return cv2.filter2D(im, -1, k / largo)


def construir_casos(base):
    return {
        "nitido":                    base,
        "rotado 15 grados":          rotar(base, 15),
        "rotado 45 grados":          rotar(base, 45),
        "perspectiva moderada":      perspectiva(base, 0.15),
        "perspectiva fuerte":        perspectiva(base, 0.28),
        "poca luz (35%)":            oscurecer(base, 0.35),
        "muy poca luz (18%)":        oscurecer(base, 0.18),
        "desenfoque k=9":            desenfoque(base, 9),
        "desenfoque k=17":           desenfoque(base, 17),
        "barrido 9 px":              barrido(base, 9),
        "barrido 15 px":             barrido(base, 15),
        "barrido 31 px":             barrido(base, 31),
        "lejano (25%)":              cv2.resize(base, None, fx=.25, fy=.25),
        "muy lejano (12%)":          cv2.resize(base, None, fx=.12, fy=.12),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guardar", help="Carpeta donde dejar las imagenes degradadas")
    args = ap.parse_args()

    base = etiqueta_base()
    casos = construir_casos(base)

    solo_zbar = Decodificador(usar_respaldo=False)
    solo_cv = Decodificador(usar_respaldo=True)
    solo_cv._con_zbar = lambda cuadro: []  # forzar el respaldo para comparar

    if args.guardar:
        carpeta = Path(args.guardar)
        carpeta.mkdir(parents=True, exist_ok=True)
        for nombre, im in casos.items():
            cv2.imwrite(str(carpeta / (nombre.replace(" ", "_") + ".png")), im)
        print(f"Imagenes guardadas en {carpeta}/\n")

    print(f"{'caso':<24} {'zbar':<8} {'opencv':<8} {'interpretado'}")
    print("-" * 62)
    fallas = []
    for nombre, im in casos.items():
        lz = solo_zbar.leer(im)
        lc = solo_cv.leer(im)

        ok_interp = "-"
        if lz:
            try:
                u = interpretar(lz[0].contenido)
                ok_interp = str(u)
            except PayloadInvalido as e:
                ok_interp = f"invalido: {e}"

        z = "OK" if lz else "falla"
        c = "OK" if lc else "falla"
        if not lz:
            fallas.append(nombre)
        print(f"{nombre:<24} {z:<8} {c:<8} {ok_interp}")

    print("\nCasos que ZBar no resuelve:")
    for f in fallas:
        print(f"  - {f}")
    print("\nSi los unicos fallos son de barrido, el problema es el montaje "
          "fisico (obturacion e iluminacion), no el software.")


if __name__ == "__main__":
    main()
