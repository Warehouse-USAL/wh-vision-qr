"""Confirmacion y deduplicacion (RF-07, RF-08, QR-15, QR-16).

Dos mecanismos distintos que suelen confundirse:

  Confirmacion: no se emite nada hasta ver el mismo contenido en N
  cuadros consecutivos. Protege contra lecturas espurias.

  Deduplicacion: una vez emitido, no se vuelve a emitir mientras la
  etiqueta siga a la vista. Protege a la base de datos del Backend de
  recibir cientos de eventos identicos porque el Rover quedo mirando
  fijo una estanteria.

Nota sobre el ensayo de laboratorio: se evaluo filtrar cuadros por
nitidez antes de intentar decodificar y se descarto. La varianza del
laplaciano no discrimina los casos que fallan: un cuadro con borroneo de
movimiento que ZBar no puede leer puntua mas alto que uno con poca luz
que si lee. Ademas la metrica depende de la escala. Intentar decodificar
directamente es barato y no miente.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class _Estado:
    consecutivos: int = 0
    emitido: bool = False
    ultimo_visto: float = field(default_factory=time.monotonic)


class Confirmador:
    def __init__(self, cuadros_necesarios: int = 3, segundos_reemision: float = 5.0):
        """
        cuadros_necesarios: cuantas veces seguidas hay que ver el mismo
            contenido antes de emitir un evento.
        segundos_reemision: cuanto tiempo debe desaparecer una etiqueta del
            campo visual para que se vuelva a considerar nueva.
        """
        self.cuadros_necesarios = max(1, cuadros_necesarios)
        self.segundos_reemision = segundos_reemision
        self._estados: Dict[str, _Estado] = {}

    def procesar(self, claves_vistas: List[str]) -> List[str]:
        """Recibe las claves presentes en el cuadro actual.
        Devuelve solo las que deben generar evento ahora."""
        ahora = time.monotonic()
        vistas = set(claves_vistas)
        a_emitir: List[str] = []

        for clave in vistas:
            est = self._estados.get(clave)
            if est is None:
                est = _Estado()
                self._estados[clave] = est
            est.consecutivos += 1
            est.ultimo_visto = ahora
            if not est.emitido and est.consecutivos >= self.cuadros_necesarios:
                est.emitido = True
                a_emitir.append(clave)

        # Las claves ausentes en este cuadro pierden su racha. Si llevan
        # suficiente tiempo fuera de vista, se olvidan y podran volver a
        # emitir cuando el Rover pase otra vez por la misma estanteria.
        for clave, est in list(self._estados.items()):
            if clave in vistas:
                continue
            est.consecutivos = 0
            if ahora - est.ultimo_visto > self.segundos_reemision:
                del self._estados[clave]

        return a_emitir

    def en_seguimiento(self) -> int:
        return len(self._estados)
