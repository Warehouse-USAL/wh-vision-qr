from vision_qr.payload import SECUENCIA, construir, interpretar
from vision_qr.recorrido import Recorrido


def leer(r, *ids):
    return [r.registrar(interpretar(construir(i))) for i in ids]


def test_vuelta_en_orden_no_avisa_nada():
    r = Recorrido()
    avances = leer(r, *SECUENCIA)
    assert not any(a.hay_advertencia for a in avances)
    assert r.vuelta_completa
    assert r.vueltas_completas == 0          # todavia no volvio a empezar


def test_detecta_una_parada_salteada():
    r = Recorrido()
    a1, a2 = leer(r, "PA1", "PA3")
    assert not a1.hay_advertencia
    assert a2.salteadas == ["PA2"]
    assert a2.hay_advertencia


def test_detecta_varias_salteadas_de_golpe():
    r = Recorrido()
    a = leer(r, "PM1")[0]                     # arranca en la mitad
    assert a.salteadas == ["PA1", "PA2", "PA3"]


def test_la_advertencia_no_rechaza_la_lectura():
    """Un salto puede ser legitimo: la parada igual queda registrada."""
    r = Recorrido()
    leer(r, "PA1", "PA3")
    assert "PA3" in r.vuelta


def test_marca_repetida():
    r = Recorrido()
    a = leer(r, "PA1", "PA2", "PA2")[2]
    assert a.repetida and a.hay_advertencia


def test_volver_a_la_primera_cierra_la_vuelta():
    r = Recorrido()
    leer(r, *SECUENCIA)
    a = leer(r, "PA1")[0]
    assert a.reinicio and r.vueltas_completas == 1
    assert r.vuelta == ["PA1"]


def test_cerrar_una_vuelta_incompleta_informa_lo_que_falto():
    r = Recorrido()
    leer(r, "PA1", "PA2")
    a = leer(r, "PA1")[0]
    assert a.salteadas == ["PA3", "PM1", "PM2", "PM3"]


def test_sin_circulo_repetir_la_primera_es_repetida():
    r = Recorrido(circular=False)
    leer(r, "PA1", "PA2")
    assert leer(r, "PA1")[0].repetida


def test_secuencia_filtrada_ignora_las_inactivas():
    """Con solo PA1 y PM2 activas, pasar por PA2 no es un salto ni cuenta."""
    r = Recorrido(secuencia=["PA1", "PM2"])
    a = leer(r, "PA1", "PA2", "PM2")
    assert not any(x.hay_advertencia for x in a)
    assert r.vuelta == ["PA1", "PM2"]


def test_siguiente_esperada():
    r = Recorrido()
    assert r.siguiente_esperada() == "PA1"
    leer(r, "PA1")
    assert r.siguiente_esperada() == "PA2"
    leer(r, "PA2", "PA3", "PM1", "PM2", "PM3")
    assert r.siguiente_esperada() == "PA1"     # circular
