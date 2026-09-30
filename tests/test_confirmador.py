import types

from vision_qr import confirmador as modulo
from vision_qr.confirmador import Confirmador


class Reloj:
    """Reloj falso: los tests no dependen de la resolucion del reloj real
    (que en Windows ronda los 15 ms) ni esperan de verdad."""
    def __init__(self):
        self.t = 1000.0
    def monotonic(self):
        return self.t


def con_reloj(monkeypatch):
    reloj = Reloj()
    monkeypatch.setattr(modulo, "time", types.SimpleNamespace(monotonic=reloj.monotonic))
    return reloj


def test_no_emite_hasta_ver_la_marca_n_veces_seguidas(monkeypatch):
    con_reloj(monkeypatch)
    c = Confirmador(cuadros_necesarios=3)
    assert c.procesar(["PA1"]) == []
    assert c.procesar(["PA1"]) == []
    assert c.procesar(["PA1"]) == ["PA1"]


def test_una_marca_sostenida_emite_una_sola_vez(monkeypatch):
    """El bug que se vio en la prueba real: mirar fijo una etiqueta no puede
    inundar al Backend con un evento por cuadro."""
    con_reloj(monkeypatch)
    c = Confirmador(cuadros_necesarios=2)
    emitidos = [e for _ in range(200) for e in c.procesar(["PA1"])]
    assert emitidos == ["PA1"]


def test_una_lectura_suelta_no_alcanza(monkeypatch):
    con_reloj(monkeypatch)
    c = Confirmador(cuadros_necesarios=3)
    c.procesar(["PA1"]); c.procesar(["PA1"])
    c.procesar([])                              # se pierde un cuadro
    assert c.procesar(["PA1"]) == []            # la racha volvio a cero


def test_paradas_distintas_se_confirman_por_separado(monkeypatch):
    con_reloj(monkeypatch)
    c = Confirmador(cuadros_necesarios=2)
    c.procesar(["PA1", "PA2"])
    assert sorted(c.procesar(["PA1", "PA2"])) == ["PA1", "PA2"]


def test_vuelve_a_emitir_tras_desaparecer_el_tiempo_configurado(monkeypatch):
    reloj = con_reloj(monkeypatch)
    c = Confirmador(cuadros_necesarios=2, segundos_reemision=5.0)
    c.procesar(["PA1"]); assert c.procesar(["PA1"]) == ["PA1"]

    reloj.t += 3.0
    c.procesar([])                              # se fue hace 3 s: todavia no cuenta como nueva
    c.procesar(["PA1"]); assert c.procesar(["PA1"]) == []

    reloj.t += 10.0
    c.procesar([])                              # se fue hace mas de 5 s: se olvida
    c.procesar(["PA1"]); assert c.procesar(["PA1"]) == ["PA1"]
