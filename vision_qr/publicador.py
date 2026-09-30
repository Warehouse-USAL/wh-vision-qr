"""Publicacion de eventos (RF-09, RF-10, QR-19 a QR-22).

La interfaz Publicador existe para que cambiar de HTTP a MQTT mas
adelante no toque una sola linea de la logica de vision. Es la decision
de diseño que el documento de requerimientos marca como no negociable,
porque el transporte definitivo depende de Comunicaciones y todavia no
esta cerrado.

El buffer offline es deliberadamente un archivo de texto con un evento
por linea. Es simple, sobrevive al reinicio, se inspecciona con cualquier
editor y preserva el orden. Para el volumen de este proyecto no hace
falta nada mas sofisticado.
"""

from __future__ import annotations
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


def construir_evento(id_rover: str, parada, lectura, contenido_crudo: str,
                     confianza: Optional[int] = None, avance=None,
                     accion: Optional[str] = None, mision: Optional[dict] = None) -> dict:
    """Arma el evento de llegada a una parada.

    Campos que importan para los otros grupos:

      parada.tipo      automatica o manual: como es la parada fisicamente.
      accion           lo que corresponde hacer segun la politica de paradas:
                       detener, esperar_operador o continuar. Es una
                       recomendacion; quien controla los motores decide.
      mision           progreso hacia el minimo de paradas pedido.
      avance           si la parada llego en el orden esperado del
                       recorrido, y cuales quedaron sin leer. Backend puede
                       usarlo para marcar vueltas incompletas. Falta en las
                       paradas inactivas, que no forman parte del recorrido
                       esperado.
    """
    evento = {
        "id_evento": str(uuid.uuid4()),
        "id_rover": id_rover,
        "marca_temporal": datetime.now(timezone.utc).isoformat(),
        "tipo": "llegada_parada",
        "contenido_crudo": contenido_crudo,
        "parada": parada.como_dict(),
        "pose": None,  # camino B, todavia no implementado (QR-37)
        "confianza": confianza,
        "reenviado": False,
    }
    if accion is not None:
        evento["accion"] = accion
    if mision is not None:
        evento["mision"] = mision
    if avance is not None:
        evento["avance"] = avance.como_dict()
    if lectura is not None:
        evento["diagnostico"] = {
            "motor": lectura.motor,
            "lado_aparente_px": round(lectura.lado_aparente, 1),
            "centro_px": lectura.centro,
        }
    return evento


def escribir_estado_local(ruta: str, evento: dict) -> bool:
    """Deja la ultima parada leida en un archivo JSON, para que el codigo de
    navegacion la consulte sin pasar por la red (QR-17).

    Se reescribe completo y de forma atomica (archivo temporal + reemplazo):
    quien lo lea nunca ve un archivo a medio escribir. Es el canal mas simple
    posible y sirve desde cualquier lenguaje. Si el equipo de vehiculos
    necesita otra cosa (un socket, el puerto serie hacia un Arduino), se
    agrega detras de la misma idea sin tocar la logica de vision.

    Un fallo al escribir NUNCA debe frenar la lectura de QR: devuelve False
    y el llamador decide si avisar.
    """
    estado = {
        "actualizado": evento["marca_temporal"],
        "id_rover": evento["id_rover"],
        "parada": evento["parada"],
        "accion": evento.get("accion"),
        "mision": evento.get("mision"),
        "avance": evento.get("avance"),
        "id_evento": evento["id_evento"],
    }
    destino = Path(ruta)
    tmp = None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(destino.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
        return True
    except OSError:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


class Publicador:
    """Interfaz. Devuelve True si el evento salio efectivamente."""

    def enviar(self, evento: dict) -> bool:
        raise NotImplementedError

    def cerrar(self) -> None:
        pass


class PublicadorConsola(Publicador):
    """Para la prueba en laptop sin ningun servidor levantado."""

    def enviar(self, evento: dict) -> bool:
        p = evento["parada"]
        marca = "AUTO" if p["tipo"] == "automatica" else "MANUAL"
        linea = f"  -> {p['id']}  [{marca}]  parada {p['orden']} de 6"
        if evento.get("accion"):
            linea += f"  | {evento['accion']}"
        m = evento.get("mision")
        if m:
            linea += f"  | mision {m['cumplidas']}/{m['requeridas']}"
            if m["cumplida"]:
                linea += " CUMPLIDA"
        av = evento.get("avance")
        if av and (av["salteadas"] or av["repetida"]):
            detalle = "repetida" if av["repetida"] else "sin leer: " + ", ".join(av["salteadas"])
            linea += f"   (!) {detalle}"
        print(linea)
        return True


class PublicadorHTTP(Publicador):
    """Transporte HTTP contra el Backend (QR-20)."""

    def __init__(self, url: str, timeout: float = 3.0, token: Optional[str] = None):
        self.url = url
        self.timeout = timeout
        self.token = token
        self._sesion = None

    def _obtener_sesion(self):
        if self._sesion is None:
            import requests
            self._sesion = requests.Session()
        return self._sesion

    def enviar(self, evento: dict) -> bool:
        try:
            sesion = self._obtener_sesion()
            cabeceras = {"Content-Type": "application/json"}
            if self.token:
                cabeceras["Authorization"] = f"Bearer {self.token}"
            r = sesion.post(self.url, json=evento, headers=cabeceras, timeout=self.timeout)
            return 200 <= r.status_code < 300
        except Exception:
            return False

    def cerrar(self) -> None:
        if self._sesion is not None:
            self._sesion.close()
            self._sesion = None


class PublicadorConBuffer(Publicador):
    """Envuelve a otro publicador y garantiza que ningun evento se pierda.

    Si el envio falla, el evento va al archivo de pendientes. En cada
    intento posterior exitoso se drena la cola en orden, marcando los
    eventos como reenviados para que el Backend sepa que no son tiempo
    real pero si historia valida.
    """

    def __init__(self, interno: Publicador, ruta_buffer: str, max_drenaje: int = 50):
        self.interno = interno
        self.ruta = Path(ruta_buffer)
        self.max_drenaje = max_drenaje
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.touch(exist_ok=True)

    def pendientes(self) -> int:
        try:
            with self.ruta.open("r", encoding="utf-8") as f:
                return sum(1 for linea in f if linea.strip())
        except FileNotFoundError:
            return 0

    def _agregar(self, evento: dict) -> None:
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # que sobreviva a un corte de energia

    def _drenar(self) -> int:
        try:
            lineas = [l for l in self.ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
        except FileNotFoundError:
            return 0
        if not lineas:
            return 0

        enviados = 0
        for linea in lineas[: self.max_drenaje]:
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                enviados += 1  # linea corrupta: descartarla y seguir
                continue
            evento["reenviado"] = True
            if not self.interno.enviar(evento):
                break  # sigue caido: conservar el resto para el proximo intento
            enviados += 1

        self._reescribir(lineas[enviados:])
        return enviados

    def _reescribir(self, restantes: List[str]) -> None:
        # Escritura atomica: si el proceso muere a mitad, el archivo original
        # queda intacto y no se pierde ningun evento pendiente.
        fd, tmp = tempfile.mkstemp(dir=str(self.ruta.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for l in restantes:
                    f.write(l + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.ruta)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def enviar(self, evento: dict) -> bool:
        # Primero se vacia la cola vieja y RECIEN despues se envia el evento
        # nuevo. Al reves (enviar el nuevo y despues drenar) el servidor
        # recibe [4, 1, 2, 3] en lugar de [1, 2, 3, 4], y RF-10 pide
        # preservar el orden.
        if self.pendientes():
            n = self._drenar()
            if n:
                print(f"  ++ enlace recuperado: {n} evento(s) reenviado(s)")
            if self.pendientes():
                # Sigue habiendo cola (el enlace sigue caido, o el drenaje
                # tiene tope por vez): el nuevo va detras para no colarse.
                self._agregar(evento)
                print(f"  .. en cola detras de otros ({self.pendientes()} pendiente/s)")
                return False

        if self.interno.enviar(evento):
            return True
        self._agregar(evento)
        print(f"  !! sin enlace: evento guardado en buffer ({self.pendientes()} pendiente/s)")
        return False

    def cerrar(self) -> None:
        self.interno.cerrar()


def construir_publicador(cfg: dict) -> Publicador:
    tipo = cfg.get("tipo", "consola")
    if tipo == "consola":
        base: Publicador = PublicadorConsola()
    elif tipo == "http":
        base = PublicadorHTTP(
            url=cfg["url"],
            timeout=cfg.get("timeout", 3.0),
            token=cfg.get("token"),
        )
    else:
        raise ValueError(f"Transporte desconocido: {tipo!r}")

    ruta = cfg.get("buffer")
    if ruta:
        return PublicadorConBuffer(base, ruta, cfg.get("max_drenaje", 50))
    return base
