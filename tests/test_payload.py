"""Contrato del contenido de las etiquetas.

Este archivo protege lo mas caro de romper: una etiqueta ya impresa y pegada
no se puede corregir, se reemplaza. Si cambia como se lee el payload, las
etiquetas del circuito quedan invalidas.
"""

import pytest

from vision_qr.payload import (
    PARADAS, SECUENCIA, PayloadInvalido, VERSION_SOPORTADA, construir, interpretar,
)


def test_las_seis_paradas_estan_en_el_catalogo():
    assert SECUENCIA == ["PA1", "PA2", "PA3", "PM1", "PM2", "PM3"]
    assert set(PARADAS) == set(SECUENCIA)


@pytest.mark.parametrize("parada", SECUENCIA)
def test_ida_y_vuelta(parada):
    """Lo que el generador imprime es exactamente lo que el lector entiende."""
    assert interpretar(construir(parada)).id == parada


def test_formato_impreso_es_estable():
    """Si esto falla, se estan invalidando las etiquetas ya pegadas."""
    assert construir("PA1") == "WH2|PA1"


def test_tipo_y_orden():
    a, m = interpretar("WH2|PA3"), interpretar("WH2|PM1")
    assert (a.tipo, a.orden, a.es_automatica) == ("automatica", 3, True)
    assert (m.tipo, m.orden, m.es_manual) == ("manual", 4, True)


def test_tolera_minusculas_y_espacios():
    assert interpretar("  WH2|pm2 \n").id == "PM2"


@pytest.mark.parametrize("contenido", [
    "https://www.google.com",       # QR comercial
    "WIFI:S:MiRed;T:WPA;P:x;;",     # QR de wifi
    "WH1|A|03|2|07",                # esquema viejo, ya no soportado
    "WH2|PA9",                      # parada que no existe
    "WH2|PA1|extra",                # campos de mas
    "WH2",                          # falta la parada
    "XX2|PA1",                      # prefijo ajeno
    "WHx|PA1",                      # version no numerica
    "WH3|PA1",                      # version futura
    "",
])
def test_rechaza_lo_que_no_es_del_proyecto(contenido):
    with pytest.raises(PayloadInvalido):
        interpretar(contenido)


def test_construir_rechaza_paradas_inexistentes():
    with pytest.raises(ValueError):
        construir("PA9")


def test_version_soportada_coincide_con_lo_impreso():
    assert construir("PA1").startswith(f"WH{VERSION_SOPORTADA}|")
