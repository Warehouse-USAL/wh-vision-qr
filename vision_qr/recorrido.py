"""Seguimiento del recorrido (nuevo con el esquema v2).

El circuito tiene un orden conocido, y eso permite algo que con una grilla
de estanterias no se podia hacer: verificar que las paradas aparezcan en
la secuencia esperada.

Sirve para detectar tres cosas que de otro modo pasan inadvertidas:

  - Una etiqueta pegada en el lugar equivocado. Es el riesgo mas serio del
    proyecto, porque el Rover cree con total confianza que esta en un lugar
    donde no esta, y nada en el software lo delata.
  - Una parada que no se leyo: el Rover paso de largo sin verla.
  - Una lectura espuria, si alguna vez ocurriera.

Importante: este modulo NO rechaza lecturas fuera de orden. Solo las marca.
Un salto puede ser legitimo (el Rover se reinicio a mitad de recorrido, un
operador lo movio a mano, esta haciendo una vuelta parcial de prueba), y
descartar una lectura correcta es peor que registrarla con una advertencia.
La decision de que hacer con la advertencia es del Backend y del grupo de
navegacion, no de la capa de vision.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .payload import SECUENCIA, Parada


@dataclass
class Avance:
    """Que significo esta lectura dentro del recorrido."""
    esperada: bool
    salteadas: List[str]
    reinicio: bool
    repetida: bool

    @property
    def hay_advertencia(self) -> bool:
        return bool(self.salteadas) or self.repetida

    def descripcion(self) -> str:
        if self.repetida:
            return "parada repetida: ya habia sido leida en esta vuelta"
        if self.salteadas:
            return "no se leyeron: " + ", ".join(self.salteadas)
        if self.reinicio:
            return "comienzo de vuelta"
        return "en orden"

    def como_dict(self) -> dict:
        return {
            "esperada": self.esperada,
            "salteadas": list(self.salteadas),
            "reinicio": self.reinicio,
            "repetida": self.repetida,
        }


class Recorrido:
    def __init__(self, secuencia: Optional[List[str]] = None, circular: bool = True):
        """
        secuencia: orden esperado de las paradas. Por defecto el del circuito.
        circular: si tras la ultima parada se espera volver a la primera.
        """
        self.secuencia = list(secuencia) if secuencia else list(SECUENCIA)
        self.circular = circular
        self.ultima: Optional[str] = None
        self.vuelta: List[str] = []
        self.vueltas_completas = 0

    def registrar(self, parada: Parada) -> Avance:
        pid = parada.id

        if pid not in self.secuencia:
            # No deberia pasar: payload.interpretar ya valido el catalogo.
            return Avance(esperada=False, salteadas=[], reinicio=False, repetida=False)

        idx = self.secuencia.index(pid)

        if self.ultima is None:
            self.vuelta = [pid]
            self.ultima = pid
            return Avance(
                esperada=(idx == 0),
                salteadas=list(self.secuencia[:idx]),
                reinicio=True,
                repetida=False,
            )

        if pid in self.vuelta:
            # Volver a la primera parada cierra la vuelta y abre otra.
            if self.circular and idx == 0:
                self.vueltas_completas += 1
                faltaron = [p for p in self.secuencia if p not in self.vuelta]
                self.vuelta = [pid]
                self.ultima = pid
                return Avance(
                    esperada=True,
                    salteadas=faltaron,
                    reinicio=True,
                    repetida=False,
                )
            return Avance(esperada=False, salteadas=[], reinicio=False, repetida=True)

        idx_ultima = self.secuencia.index(self.ultima)
        salteadas = self.secuencia[idx_ultima + 1:idx] if idx > idx_ultima else []

        self.vuelta.append(pid)
        self.ultima = pid
        return Avance(
            esperada=(idx == idx_ultima + 1),
            salteadas=list(salteadas),
            reinicio=False,
            repetida=False,
        )

    @property
    def vuelta_completa(self) -> bool:
        """True si ya se leyeron todas las paradas de la vuelta en curso.

        Distinto de vueltas_completas, que cuenta vueltas CERRADAS: una
        vuelta se cierra recien cuando el Rover vuelve a la primera parada
        y empieza la siguiente. Leer las seis y detenerse deja la vuelta
        completa pero no cerrada, y sin esta propiedad el resumen decia
        '6/6 paradas' junto a '0 vueltas', que se lee como contradiccion.
        """
        return bool(self.secuencia) and all(p in self.vuelta for p in self.secuencia)

    def siguiente_esperada(self) -> Optional[str]:
        if self.ultima is None:
            return self.secuencia[0] if self.secuencia else None
        idx = self.secuencia.index(self.ultima)
        if idx + 1 < len(self.secuencia):
            return self.secuencia[idx + 1]
        return self.secuencia[0] if self.circular else None

    def progreso(self) -> str:
        return f"{len(self.vuelta)}/{len(self.secuencia)}"
