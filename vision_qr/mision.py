"""Politica de paradas: en cuales se detiene el Rover y cuantas hacen falta.

Dos parametros, una regla:

    paradas_activas   donde puede detenerse. Por defecto, las seis.
    minimo_paradas    cuantas de esas hacen falta. 0 = todas las activas.

Ejemplos:

    activas = todas             minimo = 0   ->  las 6, es el comportamiento base
    activas = [PA1, PM2]        minimo = 0   ->  esas dos, y solo esas
    activas = todas             minimo = 4   ->  cuatro cualesquiera de las seis
    activas = [PA1,PA2,PA3,PM1] minimo = 3   ->  tres cualesquiera de esas cuatro

Este modulo NO frena al Rover. Solo decide y reporta que corresponde hacer
en cada parada; frenar es asunto del equipo de vehiculos. Por eso la salida
es una recomendacion ("detener", "esperar_operador", "continuar") y no una
orden: quien controla los motores decide si puede cumplirla.

Una parada inactiva se sigue LEYENDO y se sigue reportando. El QR esta ahi
igual, y saber por donde pasa el Rover es util aunque no se detenga. Lo que
cambia es la accion recomendada y que no cuenta para el minimo.
"""

from __future__ import annotations
from typing import Iterable, List, Optional

from .payload import PARADAS, SECUENCIA, AUTOMATICA, Parada

DETENER = "detener"                      # activa y automatica
ESPERAR_OPERADOR = "esperar_operador"    # activa y manual
CONTINUAR = "continuar"                  # no esta en las activas


class ConfiguracionInvalida(ValueError):
    """La politica de paradas pedida no se puede cumplir."""


class Mision:
    def __init__(self, activas: Optional[Iterable[str]] = None, minimo: int = 0):
        if activas is None:
            pedidas: List[str] = list(SECUENCIA)
        else:
            pedidas = [str(p).strip().upper() for p in activas]

        desconocidas = [p for p in pedidas if p not in PARADAS]
        if desconocidas:
            raise ConfiguracionInvalida(
                f"paradas_activas tiene paradas que no existen: {', '.join(desconocidas)}. "
                f"Las validas son: {', '.join(SECUENCIA)}."
            )
        if not pedidas:
            raise ConfiguracionInvalida(
                "paradas_activas quedo vacia: el Rover no se detendria en ninguna. "
                "Usa null para todas o lista al menos una."
            )

        # En el orden del circuito y sin repetidas, sin importar como se pidieron.
        conjunto = set(pedidas)
        self.activas: List[str] = [p for p in SECUENCIA if p in conjunto]

        try:
            minimo = int(minimo)
        except (TypeError, ValueError):
            raise ConfiguracionInvalida(f"minimo_paradas tiene que ser un numero entero, llego {minimo!r}.")
        if minimo < 0:
            raise ConfiguracionInvalida("minimo_paradas no puede ser negativo.")
        if minimo > len(self.activas):
            raise ConfiguracionInvalida(
                f"minimo_paradas es {minimo} pero solo hay {len(self.activas)} paradas activas "
                f"({', '.join(self.activas)}). Nunca se podria cumplir."
            )
        self.minimo = minimo

    @property
    def requeridas(self) -> int:
        """Cuantas paradas activas hay que atender para dar la mision por cumplida."""
        return self.minimo if self.minimo > 0 else len(self.activas)

    def es_activa(self, id_parada: str) -> bool:
        return id_parada in self.activas

    def accion(self, parada: Parada) -> str:
        if not self.es_activa(parada.id):
            return CONTINUAR
        return DETENER if parada.tipo == AUTOMATICA else ESPERAR_OPERADOR

    def estado(self, atendidas: Iterable[str]) -> dict:
        """Progreso de la mision, dado lo leido en la vuelta en curso.

        Las inactivas no cuentan aunque se hayan leido: el minimo se refiere
        a paradas en las que el Rover tenia que detenerse.
        """
        hechas = len({p for p in atendidas if p in self.activas})
        return {
            "activas": list(self.activas),
            "requeridas": self.requeridas,
            "cumplidas": hechas,
            "cumplida": hechas >= self.requeridas,
        }

    def descripcion(self) -> str:
        if self.minimo > 0:
            return (f"minimo {self.minimo} de {len(self.activas)} activas "
                    f"({', '.join(self.activas)})")
        if len(self.activas) == len(SECUENCIA):
            return f"todas las paradas ({len(self.activas)})"
        return f"solo {', '.join(self.activas)}"
