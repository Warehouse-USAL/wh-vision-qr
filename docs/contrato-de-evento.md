# Contrato del evento

Lo que el módulo publica cuando el Rover lee una parada. Es el punto de
acuerdo con Backend, Dashboard y las apps: los nombres son tentativos, lo que
no se negocia es que los campos estén.

## Ejemplo real

Generado por el propio código, con `paradas_activas = ["PA1","PA2","PM2"]` y
`minimo_paradas = 2`:

```json
{
  "id_evento": "a3738e2c-15b8-4529-b146-45e8bf8786b9",
  "id_rover": "rover-01",
  "marca_temporal": "2026-09-28T20:31:23.341960+00:00",
  "tipo": "llegada_parada",
  "contenido_crudo": "WH2|PA1",
  "parada": { "id": "PA1", "tipo": "automatica", "orden": 1, "version": 2 },
  "pose": null,
  "confianza": 3,
  "reenviado": false,
  "accion": "detener",
  "mision": { "activas": ["PA1", "PA2", "PM2"], "requeridas": 2, "cumplidas": 1, "cumplida": false },
  "avance": { "esperada": true, "salteadas": [], "reinicio": true, "repetida": false },
  "diagnostico": { "motor": "zbar", "lado_aparente_px": 100.0, "centro_px": [170, 130] }
}
```

## Campos

| Campo | Descripción |
|---|---|
| `id_evento` | Único, generado en el Rover. Permite descartar duplicados cuando un evento se reenvía |
| `id_rover` | Cuál de los vehículos lo emite |
| `marca_temporal` | Momento de la lectura **en el Rover**, en UTC. No es la hora de recepción |
| `tipo` | Hoy siempre `llegada_parada` |
| `contenido_crudo` | Lo que decodificó el QR, sin interpretar |
| `parada` | Cuál es (`PA1`…`PM3`), si es `automatica` o `manual`, y su lugar en el circuito |
| `pose` | Distancia y ángulo respecto de la etiqueta. `null` hasta implementar la estimación (QR-37) |
| `confianza` | Cuántos cuadros seguidos confirmaron la lectura |
| `reenviado` | `true` si salió del buffer de disco por una caída de red: no es tiempo real |
| `accion` | Lo que corresponde hacer según la política de paradas. **Recomendación, no orden** |
| `mision` | Progreso hacia el mínimo de paradas pedido |
| `avance` | Si llegó en el orden esperado y qué paradas quedaron sin leer. **Falta en las paradas inactivas** |
| `diagnostico` | Datos para depurar; no hace falta consumirlos |

### `accion`

| Valor | Cuándo |
|---|---|
| `detener` | Parada activa y automática |
| `esperar_operador` | Parada activa y manual |
| `continuar` | La parada no está entre las activas |

El módulo **no frena al Rover**. Quien controla los motores decide si puede
cumplir la recomendación.

### `avance`

No rechaza nada: marca. Una parada fuera de orden puede ser legítima (el Rover
se reinició, alguien lo movió a mano), y descartar una lectura correcta es peor
que registrarla con una advertencia. Qué hacer con `salteadas` lo deciden
Backend y navegación.

## Por decidir con Backend

1. **Los campos nuevos.** `accion` y `mision` se agregaron después del primer
   borrador del contrato: confirmar que los aceptan o cómo los quieren.
2. **Si la asociación parada–producto es fija o cambia con el tiempo.** El QR
   identifica el lugar, no el producto: el producto de cada parada vive en su
   base de datos. Si cambia, conviene guardar desde cuándo y hasta cuándo valió
   cada asociación, para poder saber qué había en una parada *en el momento* de
   un evento viejo.
3. **Orden de llegada.** El buffer reenvía en orden cronológico, pero la red
   puede reordenar. Ordenar por `marca_temporal`, no por hora de recepción.

## Estado local

Además de la red, el módulo puede dejar la última parada en un archivo
(`estado_local` en el config), pensado para el código de navegación del
vehículo. Se reescribe completo y de forma atómica en cada parada: quien lo lea
nunca ve un archivo a medio escribir.

```json
{
  "actualizado": "2026-09-28T20:31:23.341960+00:00",
  "id_rover": "rover-01",
  "parada": { "id": "PA1", "tipo": "automatica", "orden": 1, "version": 2 },
  "accion": "detener",
  "mision": { "activas": ["PA1", "PA2", "PM2"], "requeridas": 2, "cumplidas": 1, "cumplida": false },
  "avance": { "esperada": true, "salteadas": [], "reinicio": true, "repetida": false },
  "id_evento": "a3738e2c-15b8-4529-b146-45e8bf8786b9"
}
```

Si el equipo de vehículos necesita otro canal (un socket, el puerto serie hacia
un Arduino), se agrega detrás de la misma idea sin tocar la lógica de visión.
Hay que definir con ellos cuál.
