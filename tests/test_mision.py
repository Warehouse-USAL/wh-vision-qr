import pytest

from vision_qr.mision import (
    CONTINUAR, DETENER, ESPERAR_OPERADOR, ConfiguracionInvalida, Mision,
)
from vision_qr.payload import SECUENCIA, interpretar, construir


def parada(pid):
    return interpretar(construir(pid))


class TestPorDefecto:
    def test_son_las_seis_y_hacen_falta_todas(self):
        m = Mision()
        assert m.activas == SECUENCIA
        assert m.requeridas == 6

    def test_acciones_segun_tipo(self):
        m = Mision()
        assert m.accion(parada("PA1")) == DETENER
        assert m.accion(parada("PM1")) == ESPERAR_OPERADOR


class TestParadasEspecificas:
    def test_solo_en_las_pedidas(self):
        m = Mision(["PA1", "PM2"])
        assert m.activas == ["PA1", "PM2"]
        assert m.requeridas == 2
        assert m.accion(parada("PA1")) == DETENER
        assert m.accion(parada("PM2")) == ESPERAR_OPERADOR
        assert m.accion(parada("PA2")) == CONTINUAR
        assert m.accion(parada("PM3")) == CONTINUAR

    def test_orden_del_circuito_sin_importar_como_se_pidieron(self):
        assert Mision(["PM2", "PA1", "PA1"]).activas == ["PA1", "PM2"]

    def test_tolera_minusculas(self):
        assert Mision(["pa1", " pm3 "]).activas == ["PA1", "PM3"]


class TestMinimo:
    def test_minimo_entre_todas(self):
        m = Mision(None, 4)
        assert m.requeridas == 4
        assert not m.estado(["PA1", "PA2", "PA3"])["cumplida"]
        assert m.estado(["PA1", "PA2", "PA3", "PM1"])["cumplida"]

    def test_minimo_entre_algunas(self):
        m = Mision(["PA1", "PA2", "PA3", "PM1"], 3)
        assert m.estado(["PA1", "PM1", "PA3"])["cumplida"]

    def test_minimo_cero_exige_todas_las_activas(self):
        m = Mision(["PA1", "PM2"], 0)
        assert not m.estado(["PA1"])["cumplida"]
        assert m.estado(["PA1", "PM2"])["cumplida"]

    def test_las_inactivas_no_cuentan_aunque_se_hayan_leido(self):
        m = Mision(["PA1", "PA2"], 2)
        e = m.estado(["PA1", "PM1", "PM2", "PM3"])
        assert e["cumplidas"] == 1
        assert not e["cumplida"]

    def test_no_cuenta_dos_veces_la_misma(self):
        assert Mision(None, 2).estado(["PA1", "PA1", "PA1"])["cumplidas"] == 1


class TestConfiguracionInvalida:
    @pytest.mark.parametrize("activas", [["PA9"], ["PA1", "XX"], ["PM4"]])
    def test_parada_inexistente(self, activas):
        with pytest.raises(ConfiguracionInvalida, match="no existen"):
            Mision(activas)

    def test_lista_vacia(self):
        with pytest.raises(ConfiguracionInvalida, match="vacia"):
            Mision([])

    def test_minimo_imposible(self):
        with pytest.raises(ConfiguracionInvalida, match="Nunca se podria cumplir"):
            Mision(["PA1", "PA2"], 3)

    def test_minimo_negativo(self):
        with pytest.raises(ConfiguracionInvalida):
            Mision(None, -1)

    def test_minimo_no_numerico(self):
        with pytest.raises(ConfiguracionInvalida):
            Mision(None, "muchos")


def test_descripcion_legible():
    assert "todas" in Mision().descripcion()
    assert "solo PA1, PM2" == Mision(["PA1", "PM2"]).descripcion()
    assert "minimo 3 de 6" in Mision(None, 3).descripcion()
