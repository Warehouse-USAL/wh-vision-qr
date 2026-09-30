"""Interpretacion del contenido de un QR del proyecto.

Esquema v2 (recorrido con paradas):

    WH2|PA1
     |   `-- identificador de parada
     `------ prefijo + version de esquema

El recorrido educativo tiene seis paradas fijas:

    PA1, PA2, PA3   automaticas: el Rover se detiene solo al leerlas
    PM1, PM2, PM3   manuales: requieren intervencion de un operador

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

PREFIJO = "WH"
VERSION_SOPORTADA = 2
SEPARADOR = "|"

AUTOMATICA = "automatica"
MANUAL = "manual"

# Catalogo maestro de paradas. Cualquier identificador fuera de este
# conjunto es un error de lectura o una etiqueta ajena al circuito.
PARADAS = {
    "PA1": AUTOMATICA,
    "PA2": AUTOMATICA,
    "PA3": AUTOMATICA,
    "PM1": MANUAL,
    "PM2": MANUAL,
    "PM3": MANUAL,
}

# Orden en que el Rover deberia encontrarlas recorriendo el circuito en U:
# entra arriba a la derecha, avanza hacia la izquierda, baja y vuelve por
# abajo hacia la derecha.
SECUENCIA = ["PA1", "PA2", "PA3", "PM1", "PM2", "PM3"]


class PayloadInvalido(Exception):
    """El contenido no corresponde a una etiqueta del proyecto."""


@dataclass(frozen=True)
class Parada:
    id: str
    tipo: str
    orden: int
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

    def __str__(self) -> str:
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
            f"parada desconocida: {id_parada!r} (validas: {', '.join(SECUENCIA)})"
        )

    return Parada(
        id=id_parada,
        tipo=PARADAS[id_parada],
        orden=SECUENCIA.index(id_parada) + 1,
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
            f"Parada desconocida: {id_parada!r}. Validas: {', '.join(SECUENCIA)}"
        )
    return f"{PREFIJO}{VERSION_SOPORTADA}{SEPARADOR}{id_parada}"
