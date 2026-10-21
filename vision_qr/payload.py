"""Interpretacion del contenido de un QR del proyecto.

Esquema v2 (recorrido con paradas):

    WH2|PA1
     |   `-- identificador de parada
     `------ prefijo + version de esquema

El recorrido tiene paradas fijas (layout de la maqueta, lamina 1):

    PA1, PA2, PA3   automaticas: el Rover se detiene solo al leerlas
    PM1, PM2, PM3   manuales: requieren intervencion de un operador
    D1              descarga: ultima parada del circuito, se confirma por QR
    P1, P2          home: donde arranca y termina cada vehiculo. Cada Rover
                    tiene UN home (el config dice cual); no forman parte de
                    la secuencia comun, porque el circuito tiene dos rieles
                    y cada vehiculo vuelve al suyo.

Por que el payload es tan corto: el QR identifica una parada, no la
describe. Que hay en esa parada, en que orden va y que debe hacer el Rover
alli vive en la configuracion y en el Backend. Meter datos de negocio en
una etiqueta impresa obliga a reimprimirla cada vez que algo cambia.

Ademas menos datos significa un codigo con menos modulos, y un codigo con
menos modulos se lee desde mas lejos con el mismo tamano de etiqueta. Para
un Rover en movimiento eso es una ventaja concreta, no una sutileza.

El prefijo cumple RF-04: cualquier QR que no lo tenga se descarta sin
generar evento, asi el Rover nunca reporta el codigo de un envase
comercial que quedo dando vueltas por el circuito.
"""

from dataclasses import dataclass, asdict
from typing import Optional

PREFIJO = "WH"
VERSION_SOPORTADA = 2
SEPARADOR = "|"

AUTOMATICA = "automatica"
MANUAL = "manual"
DESCARGA = "descarga"
HOME = "home"

# Catalogo maestro de paradas. Cualquier identificador fuera de este
# conjunto es un error de lectura o una etiqueta ajena al circuito.
PARADAS = {
    "PA1": AUTOMATICA,
    "PA2": AUTOMATICA,
    "PA3": AUTOMATICA,
    "PM1": MANUAL,
    "PM2": MANUAL,
    "PM3": MANUAL,
    "D1": DESCARGA,
    "P1": HOME,
    "P2": HOME,
}

# Orden en que el Rover deberia encontrar las paradas del circuito comun
# (sentido antihorario): abajo de izquierda a derecha (A1 -> A3), sube por
# la derecha y vuelve por arriba de derecha a izquierda (M1 -> M3), y termina
# en la descarga D1. Los home no estan aca: son uno por vehiculo.
SECUENCIA = ["PA1", "PA2", "PA3", "PM1", "PM2", "PM3", "D1"]

# Paradas de home. Cada vehiculo usa una sola (config: "parada_home").
HOMES = ["P1", "P2"]

# Todas las etiquetas del proyecto, en el orden en que se listan e imprimen.
CATALOGO = SECUENCIA + HOMES


class PayloadInvalido(Exception):
    """El contenido no corresponde a una etiqueta del proyecto."""


@dataclass(frozen=True)
class Parada:
    id: str
    tipo: str
    orden: Optional[int]    # lugar en SECUENCIA (desde 1); None en los home
    version: int

    @property
    def es_automatica(self) -> bool:
        return self.tipo == AUTOMATICA

    @property
    def es_manual(self) -> bool:
        return self.tipo == MANUAL

    def clave(self) -> str:
        """Identificador estable, usado para deduplicar lecturas."""
        return self.id

    def como_dict(self) -> dict:
        return asdict(self)

    @property
    def es_home(self) -> bool:
        return self.tipo == HOME

    @property
    def es_descarga(self) -> bool:
        return self.tipo == DESCARGA

    def __str__(self) -> str:
        if self.orden is None:
            return f"{self.id} ({self.tipo})"
        return f"{self.id} ({self.tipo}, {self.orden} de {len(SECUENCIA)})"


def interpretar(contenido: str) -> Parada:
    """Convierte el texto decodificado en una Parada.

    Lanza PayloadInvalido si el contenido no pertenece al proyecto o esta
    mal formado. El llamador debe tratar esa excepcion como un descarte
    silencioso, no como un error del sistema.
    """
    if not isinstance(contenido, str) or not contenido:
        raise PayloadInvalido("contenido vacio")

    partes = contenido.strip().split(SEPARADOR)
    if len(partes) != 2:
        raise PayloadInvalido(f"se esperaban 2 campos, llegaron {len(partes)}")

    cabecera, id_parada = partes

    if not cabecera.startswith(PREFIJO):
        raise PayloadInvalido(f"prefijo desconocido: {cabecera!r}")

    try:
        version = int(cabecera[len(PREFIJO):])
    except ValueError:
        raise PayloadInvalido(f"version no numerica en {cabecera!r}")

    if version != VERSION_SOPORTADA:
        raise PayloadInvalido(
            f"version {version} no soportada (esta build entiende v{VERSION_SOPORTADA})"
        )

    id_parada = id_parada.strip().upper()
    if id_parada not in PARADAS:
        raise PayloadInvalido(
            f"parada desconocida: {id_parada!r} (validas: {', '.join(CATALOGO)})"
        )

    return Parada(
        id=id_parada,
        tipo=PARADAS[id_parada],
        orden=SECUENCIA.index(id_parada) + 1 if id_parada in SECUENCIA else None,
        version=version,
    )


def construir(id_parada: str) -> str:
    """Genera el texto a codificar en una etiqueta.

    Lo usa el generador de etiquetas, para que el formato viva en un solo
    lugar y el generador nunca pueda desincronizarse del lector.
    """
    id_parada = str(id_parada).strip().upper()
    if id_parada not in PARADAS:
        raise ValueError(
            f"Parada desconocida: {id_parada!r}. Validas: {', '.join(CATALOGO)}"
        )
    return f"{PREFIJO}{VERSION_SOPORTADA}{SEPARADOR}{id_parada}"
