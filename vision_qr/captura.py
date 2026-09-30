"""Capa de captura (RF-01, QR-07).

El resto del sistema nunca sabe de donde viene la imagen. Cuando el
modulo migre a la Raspberry Pi, lo unico que cambia es la clase que se
instancia, elegida por configuracion. Ningun otro archivo se toca.
"""

from __future__ import annotations
import glob
import sys
import threading
import time
from typing import Iterator, Optional

import cv2
import numpy as np


class FuenteImagen:
    """Interfaz comun. Toda fuente entrega cuadros BGR de OpenCV."""

    def cuadros(self) -> Iterator[np.ndarray]:
        raise NotImplementedError

    def cerrar(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()


_BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY),
    "msmf": getattr(cv2, "CAP_MSMF", cv2.CAP_ANY),
    "v4l2": getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),
    "avfoundation": getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY),
}


def _resolver_backend(nombre):
    if nombre is None:
        return backend_por_defecto()
    clave = str(nombre).lower()
    if clave not in _BACKENDS:
        raise ValueError(f"Backend desconocido: {nombre!r}. Opciones: {list(_BACKENDS)}")
    return _BACKENDS[clave]


def backend_por_defecto() -> int:
    """Elige el backend de captura segun el sistema operativo.

    En Windows importa mucho. El backend por defecto (Media Foundation)
    tarda varios segundos en abrir la camara y a menudo ignora los
    pedidos de resolucion. DirectShow abre casi instantaneo y respeta
    ancho y alto. En Linux y macOS el backend automatico anda bien.
    """
    if sys.platform.startswith("win"):
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


class FuenteWebcam(FuenteImagen):
    """Webcam de la laptop o camara USB del Rover.

    Nota sobre el articulo de Scanbot: alli se afirma que hace falta
    compilar OpenCV con GStreamer para leer de camara. Eso aplica a
    pipelines de GStreamer especificos. Para una webcam comun en Linux,
    macOS o Windows, VideoCapture funciona con el backend nativo del
    sistema sin recompilar nada.
    """

    def __init__(self, indice: int = 0, ancho: int = 640, alto: int = 480,
                 fps: int = 30, backend: Optional[str] = None,
                 fourcc: Optional[str] = None):
        """fourcc: codec que se le pide a la camara, por ejemplo "MJPG".

        Importa en la Raspberry Pi 3. Una camara USB en YUYV sin comprimir a
        640x480 y 30 fps mueve unos 18 MB/s por un bus USB 2.0 que la Pi 3
        comparte con la red. En MJPG la camara comprime y el bus queda libre,
        a cambio de un poco de CPU para descomprimir. Si la camara no lo
        soporta, OpenCV ignora el pedido y sigue con el que tenga.
        """
        self.indice = indice
        self.ancho = ancho
        self.alto = alto
        self.fps = fps
        self.backend = _resolver_backend(backend)
        self.fourcc = fourcc
        self.cap: Optional[cv2.VideoCapture] = None

    def _abrir(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.indice, self.backend)
        if not cap.isOpened():
            raise RuntimeError(
                f"No se pudo abrir la camara {self.indice}.\n"
                "Cosas a revisar:\n"
                "  - Que no este en uso por Teams, Zoom, OBS o la app Camara.\n"
                "  - En Windows: Configuracion > Privacidad > Camara, y activar\n"
                "    'Permitir que las aplicaciones de escritorio accedan a la camara'.\n"
                "  - Que el indice sea el correcto: proba con buscar_camaras.py."
            )
        # El codec se pide ANTES que la resolucion: al reves, muchas camaras
        # UVC negocian mal la combinacion y se quedan con el modo lento.
        if self.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        # Buffer chico: preferimos el cuadro mas reciente antes que uno viejo.
        # Un Rover en movimiento no gana nada procesando imagenes atrasadas.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def cuadros(self) -> Iterator[np.ndarray]:
        self.cap = self._abrir()
        while True:
            ok, cuadro = self.cap.read()
            if not ok:
                # RF-07 / QR-35: un fallo de camara no debe matar el proceso.
                time.sleep(0.5)
                self.cerrar()
                self.cap = self._abrir()
                continue
            yield cuadro

    def cerrar(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class FuenteArchivos(FuenteImagen):
    """Reproduce imagenes de una carpeta como si fueran cuadros.

    Sirve para probar sin camara, para las pruebas automatizadas (QR-39)
    y para reproducir una situacion de falla capturada en el warehouse.
    """

    def __init__(self, patron: str, repeticiones: int = 1, pausa: float = 0.0):
        self.patron = patron
        self.repeticiones = repeticiones
        self.pausa = pausa

    def cuadros(self) -> Iterator[np.ndarray]:
        rutas = sorted(glob.glob(self.patron))
        if not rutas:
            raise RuntimeError(f"No hay imagenes que coincidan con {self.patron!r}")
        for ruta in rutas:
            imagen = cv2.imread(ruta)
            if imagen is None:
                continue
            for _ in range(self.repeticiones):
                if self.pausa:
                    time.sleep(self.pausa)
                yield imagen


class FuenteVideo(FuenteImagen):
    """Reproduce un archivo de video como si fuera la camara en vivo.

    Es la pieza que permite desarrollar en Linux sin pelearse con el
    pasaje de la camara a una maquina virtual: se graba un clip una vez
    (en Windows, o directamente sobre el Rover) y se reproduce cuantas
    veces haga falta, siempre igual.

    Ademas vuelve reproducibles las pruebas: un clip del Rover en
    movimiento es la unica forma honesta de medir la tasa de acierto con
    barrido real, y se puede volver a correr despues de cada cambio.
    """

    def __init__(self, ruta: str, repetir: bool = False,
                 velocidad: float = 1.0, saltar: int = 0,
                 ancho: Optional[int] = None, alto: Optional[int] = None):
        """ancho / alto: reducen cada cuadro antes de procesarlo.

        Sirve para responder "se leeria esto a la resolucion de la Pi?" con
        un clip grabado en mejor calidad. Una GoPro graba en 1080p; la Pi 3
        va a recibir 640x480. Procesar el clip a resolucion original mide
        el mejor caso, no el real.

        Si se da solo el ancho, el alto se calcula conservando la
        proporcion: estirar un clip 16:9 a 4:3 deforma los cuadrados del QR
        y falsea la prueba.
        """
        self.ruta = ruta
        self.repetir = repetir
        self.velocidad = max(velocidad, 0.0)
        self.saltar = max(saltar, 0)
        self.ancho = int(ancho) if ancho else None
        self.alto = int(alto) if alto else None
        self.cap: Optional[cv2.VideoCapture] = None

    def _reducir(self, cuadro: np.ndarray) -> np.ndarray:
        if not self.ancho and not self.alto:
            return cuadro
        h, w = cuadro.shape[:2]
        ancho = self.ancho or round(w * self.alto / h)
        alto = self.alto or round(h * self.ancho / w)
        if (ancho, alto) == (w, h):
            return cuadro
        # INTER_AREA es el filtro correcto para achicar: promedia en lugar
        # de saltear pixeles, que es lo que hace un sensor real mas chico.
        return cv2.resize(cuadro, (ancho, alto), interpolation=cv2.INTER_AREA)

    def cuadros(self) -> Iterator[np.ndarray]:
        while True:
            self.cap = cv2.VideoCapture(self.ruta)
            if not self.cap.isOpened():
                raise RuntimeError(f"No se pudo abrir el video {self.ruta!r}")

            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            # velocidad 0 = tan rapido como se pueda, util para medir
            # cuantos cuadros por segundo aguanta el pipeline.
            espera = (1.0 / fps) / self.velocidad if self.velocidad else 0.0

            n = 0
            while True:
                ok, cuadro = self.cap.read()
                if not ok:
                    break
                n += 1
                if self.saltar and n % (self.saltar + 1) != 1:
                    continue
                if espera:
                    time.sleep(espera)
                yield self._reducir(cuadro)

            self.cerrar()
            if not self.repetir:
                return

    def cerrar(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class FuenteRed(FuenteImagen):
    """Lee el video MJPEG que emite transmitir_camara.py desde otra maquina.

    Sirve para probar la Raspberry Pi en vivo con la camara de la laptop. No
    usa el FFmpeg de OpenCV: corta el flujo HTTP buscando los marcadores de
    JPEG, asi que no depende de como se compilo OpenCV en cada plataforma.

    Un hilo lee siempre; cuadros() entrega el MAS RECIENTE y descarta los
    que no llego a procesar. Si la Pi va mas lenta que la camara, atrasar la
    imagen no sirve de nada: lo mismo que hace FuenteWebcam con su buffer de 1.

    Si se corta la conexion reintenta solo (RF-07): apagar la laptop un rato
    no debe matar el proceso de la Pi.
    """

    def __init__(self, url: str, reintento: float = 2.0, timeout: float = 5.0):
        self.url = url
        self.reintento = reintento
        self.timeout = timeout
        self._ultimo: Optional[np.ndarray] = None
        self._numero = 0
        self._cond = threading.Condition()
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self.error: Optional[str] = None

    def _leer_flujo(self) -> None:
        import requests
        with requests.get(self.url, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            self.error = None
            resto = b""
            for trozo in r.iter_content(chunk_size=4096):
                if self._parar.is_set():
                    return
                resto += trozo
                while True:
                    ini = resto.find(b"\xff\xd8")
                    if ini < 0:
                        resto = resto[-1:]
                        break
                    fin = resto.find(b"\xff\xd9", ini + 2)
                    if fin < 0:
                        resto = resto[ini:]
                        break
                    jpg, resto = resto[ini:fin + 2], resto[fin + 2:]
                    cuadro = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if cuadro is None:
                        continue
                    with self._cond:
                        self._ultimo = cuadro
                        self._numero += 1
                        self._cond.notify_all()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                self._leer_flujo()
            except Exception as e:  # red caida, servidor apagado, timeout
                self.error = f"{type(e).__name__}: {e}"
            if not self._parar.wait(self.reintento):
                continue

    def cuadros(self) -> Iterator[np.ndarray]:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        visto = 0
        while True:
            with self._cond:
                if not self._cond.wait_for(lambda: self._numero != visto, timeout=1.0):
                    continue
                visto = self._numero
                cuadro = self._ultimo
            yield cuadro

    def cerrar(self) -> None:
        self._parar.set()
        # Esperar al hilo: cortar el proceso con el decodificador a medio
        # cuadro hace que el interprete aborte con un mensaje feo al salir.
        if self._hilo is not None and self._hilo.is_alive():
            self._hilo.join(timeout=2.0)


class FuentePicamera(FuenteImagen):
    """Camara CSI de la Raspberry Pi mediante picamera2.

    Esta clase existe ya para dejar cerrado el contrato de la Fase 3
    (QR-26). En la laptop no se importa picamera2, por eso el import
    esta dentro del metodo: la dependencia solo se exige donde se usa.
    """

    def __init__(self, ancho: int = 640, alto: int = 480):
        self.ancho = ancho
        self.alto = alto
        self.cam = None

    def cuadros(self) -> Iterator[np.ndarray]:
        try:
            from picamera2 import Picamera2
        except ImportError as e:
            raise RuntimeError(
                "picamera2 no esta disponible. Esta fuente solo corre sobre "
                "Raspberry Pi OS. En la laptop usa la fuente 'webcam'."
            ) from e

        self.cam = Picamera2()
        cfg = self.cam.create_preview_configuration(
            main={"size": (self.ancho, self.alto), "format": "RGB888"}
        )
        self.cam.configure(cfg)
        self.cam.start()
        time.sleep(1.0)  # dejar que el autoexposicion se estabilice
        while True:
            yield self.cam.capture_array()

    def cerrar(self) -> None:
        if self.cam is not None:
            self.cam.stop()
            self.cam = None


def construir_fuente(cfg: dict) -> FuenteImagen:
    """Fabrica la fuente segun configuracion (RF-14)."""
    tipo = cfg.get("tipo", "webcam")
    if tipo == "webcam":
        return FuenteWebcam(
            indice=cfg.get("indice", 0),
            ancho=cfg.get("ancho", 640),
            alto=cfg.get("alto", 480),
            fps=cfg.get("fps", 30),
            backend=cfg.get("backend"),
            fourcc=cfg.get("fourcc"),
        )
    if tipo == "archivos":
        return FuenteArchivos(
            patron=cfg["patron"],
            repeticiones=cfg.get("repeticiones", 1),
            pausa=cfg.get("pausa", 0.0),
        )
    if tipo == "video":
        return FuenteVideo(
            ruta=cfg["ruta"],
            repetir=cfg.get("repetir", False),
            velocidad=cfg.get("velocidad", 1.0),
            saltar=cfg.get("saltar", 0),
            ancho=cfg.get("ancho"),
            alto=cfg.get("alto"),
        )
    if tipo == "red":
        return FuenteRed(url=cfg["url"], reintento=cfg.get("reintento", 2.0))
    if tipo == "picamera":
        return FuentePicamera(ancho=cfg.get("ancho", 640), alto=cfg.get("alto", 480))
    raise ValueError(f"Fuente desconocida: {tipo!r}")
