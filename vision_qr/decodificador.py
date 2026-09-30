"""Deteccion y decodificacion de QR (RF-02, RF-03, RF-05, QR-08, QR-09).

Motor principal: ZBar via pyzbar.
Respaldo: detector nativo de OpenCV, solo si el principal no encuentra nada.

Ambos se filtran a simbolos QR exclusivamente. El proyecto no usa codigos
de barras lineales, y permitir otros formatos solo agrega superficie para
falsos positivos con envases comerciales.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from pyzbar.pyzbar import decode as zbar_decode, ZBarSymbol


@dataclass
class Lectura:
    contenido: str
    esquinas: List[Tuple[int, int]] = field(default_factory=list)
    motor: str = "zbar"

    @property
    def centro(self) -> Tuple[int, int]:
        if not self.esquinas:
            return (0, 0)
        xs = [p[0] for p in self.esquinas]
        ys = [p[1] for p in self.esquinas]
        return (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))

    @property
    def lado_aparente(self) -> float:
        """Longitud media del lado en pixeles.

        Es el insumo de la estimacion de distancia del camino B (QR-37).
        Se calcula ya aca porque las esquinas estan disponibles sin costo
        adicional, aunque todavia no se use.
        """
        if len(self.esquinas) != 4:
            return 0.0
        pts = self.esquinas
        lados = [
            float(np.linalg.norm(np.array(pts[i]) - np.array(pts[(i + 1) % 4])))
            for i in range(4)
        ]
        return sum(lados) / 4.0


class Decodificador:
    def __init__(self, usar_respaldo: bool = True):
        self.usar_respaldo = usar_respaldo
        self._det_cv = cv2.QRCodeDetector()
        self.conteo_motor = {"zbar": 0, "opencv": 0}

    def leer(self, cuadro: np.ndarray) -> List[Lectura]:
        lecturas = self._con_zbar(cuadro)
        if lecturas:
            self.conteo_motor["zbar"] += len(lecturas)
            return lecturas

        if self.usar_respaldo:
            lecturas = self._con_opencv(cuadro)
            self.conteo_motor["opencv"] += len(lecturas)
        return lecturas

    def _con_zbar(self, cuadro: np.ndarray) -> List[Lectura]:
        # ZBar trabaja sobre escala de grises; convertir explicitamente
        # evita que lo haga internamente en cada llamada.
        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY) if cuadro.ndim == 3 else cuadro
        salida = []
        for s in zbar_decode(gris, symbols=[ZBarSymbol.QRCODE]):
            try:
                texto = s.data.decode("utf-8")
            except UnicodeDecodeError:
                continue  # binario: no es una etiqueta nuestra
            esquinas = [(p.x, p.y) for p in s.polygon]
            salida.append(Lectura(contenido=texto, esquinas=esquinas, motor="zbar"))
        return salida

    def _con_opencv(self, cuadro: np.ndarray) -> List[Lectura]:
        try:
            ok, textos, puntos, _ = self._det_cv.detectAndDecodeMulti(cuadro)
        except cv2.error:
            return []
        if not ok or textos is None:
            return []

        salida = []
        for i, texto in enumerate(textos):
            if not texto:
                continue
            esquinas = []
            if puntos is not None and i < len(puntos):
                esquinas = [(int(x), int(y)) for x, y in puntos[i]]
            salida.append(Lectura(contenido=texto, esquinas=esquinas, motor="opencv"))
        return salida


def anotar(cuadro: np.ndarray, lecturas: List[Lectura], etiqueta_extra: str = "") -> np.ndarray:
    """Dibuja el contorno y el contenido sobre el cuadro (RF-13, QR-10).

    Se dibuja el poligono real de cuatro puntos y no un rectangulo recto:
    con el Rover en angulo, el rectangulo recto miente sobre lo que el
    decodificador realmente vio, y eso confunde al diagnosticar.
    """
    salida = cuadro.copy()
    for l in lecturas:
        if len(l.esquinas) >= 4:
            pts = np.array(l.esquinas, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(salida, [pts], True, (0, 220, 0), 2)
            x, y = l.esquinas[0]
        else:
            x, y = 10, 30
        cv2.putText(salida, f"{l.contenido} [{l.motor}]", (x, max(y - 10, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 0), 2)
    if etiqueta_extra:
        cv2.putText(salida, etiqueta_extra, (10, salida.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
    return salida
