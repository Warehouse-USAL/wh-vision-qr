"""Vista en vivo por navegador (vision_qr/vista_web.py)."""

import time
import urllib.request

import cv2
import numpy as np

from vision_qr.vista_web import VistaWeb


def _abrir():
    return VistaWeb(0, fps_max=1000)  # puerto 0: el sistema elige uno libre


def _puerto(v):
    return v._servidor.server_address[1]


def test_no_trabaja_si_nadie_mira():
    """Con la CPU de una Pi 3, dibujar y comprimir para nadie es desperdicio."""
    v = _abrir()
    try:
        assert v.quiere_cuadro() is False
    finally:
        v.cerrar()


def test_entrega_un_cuadro_jpeg_a_quien_mira():
    v = _abrir()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{_puerto(v)}/video", timeout=3)
        for _ in range(50):              # esperar a que el cliente quede registrado
            if v.quiere_cuadro():
                break
            time.sleep(0.05)
        assert v.quiere_cuadro() is True
        v.publicar(np.full((60, 80, 3), 120, np.uint8))
        datos = b""
        while b"\xff\xd9" not in datos:
            datos += resp.read1(4096)
        i = datos.find(b"\xff\xd8")
        j = datos.find(b"\xff\xd9", i)
        img = cv2.imdecode(np.frombuffer(datos[i:j + 2], np.uint8), cv2.IMREAD_COLOR)
        assert img.shape == (60, 80, 3)
        resp.close()
    finally:
        v.cerrar()


def test_la_pagina_principal_responde():
    v = _abrir()
    try:
        html = urllib.request.urlopen(f"http://127.0.0.1:{_puerto(v)}/", timeout=3).read()
        assert b"/video" in html
    finally:
        v.cerrar()


def test_limita_los_cuadros_por_segundo():
    v = VistaWeb(0, fps_max=2)
    try:
        v._clientes = 1                  # simula un espectador
        v.publicar(np.zeros((10, 10, 3), np.uint8))
        assert v.quiere_cuadro() is False   # recien se emitio uno
        time.sleep(0.6)
        assert v.quiere_cuadro() is True
    finally:
        v.cerrar()
