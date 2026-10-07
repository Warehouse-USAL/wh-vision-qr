"""Broker MQTT local, para probar el nodo sin la central real.

Solo para pruebas en la laptop. En el Rover el broker es el de la central
(RabbitMQ con el plugin MQTT). Acepta cualquier usuario y clave.

Instalacion (una vez):  pip install amqtt
Uso:                    python broker_prueba.py            # puerto 1883
                        python broker_prueba.py --puerto 18830

Si Windows pregunta por el firewall, permitir en redes privadas: la Pi se
conecta a esta laptop desde afuera.
"""

import argparse
import asyncio
import sys


async def correr(puerto: int) -> None:
    from amqtt.broker import Broker
    cfg = {
        "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{puerto}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }
    broker = Broker(cfg)
    await broker.start()
    print(f"Broker de prueba escuchando en el puerto {puerto}. Ctrl+C para cortar.")
    while True:
        await asyncio.sleep(3600)


def main() -> int:
    ap = argparse.ArgumentParser(description="Broker MQTT de prueba")
    ap.add_argument("--puerto", type=int, default=1883)
    args = ap.parse_args()
    try:
        import amqtt  # noqa: F401
    except ImportError:
        sys.exit("Falta amqtt. Instalalo con: pip install amqtt")
    try:
        asyncio.run(correr(args.puerto))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
