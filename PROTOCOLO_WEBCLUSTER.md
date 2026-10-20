# Contrato entre WebClusterURE y el GW FlexRadio

Referencia obtenida el 20 de octubre de 2026 mediante una lectura puntual del
frontend en `../../ure/webcluster.ure.es`, rama `develop`. Describe el código
local consultado, no una verificación del frontend publicado ni del protocolo
oficial de FlexRadio. No se modificó el frontend ni se conectó con hardware.

## Fuentes y alcance

Archivos del frontend, relativos a ese repositorio:

| Fuente | Responsabilidad consultada |
| --- | --- |
| `static/js/webcluster-connector-service.js` | Socket, configuración, mensajes, cola, estado CAT y envío de QSO |
| `static/js/cat.js` | Delegación del CAT, indicadores y selección de frecuencia |
| `static/js/worked-qso-service.js` | Generación ADIF, envío al guardar y marca de exportado |
| `static/index.html` | Inclusión de los módulos |

Es un contrato compartido de datos y servicios de la web; no se ha definido un
protocolo distinto para móvil. No se revisaron dominios ajenos al conector.
La comparación con el GW corresponde a `app.py` de este directorio.

## Arquitectura y activación

```text
WebClusterURE ── WebSocket JSON ── GW app.py ── TCP ── FlexRadio
                                      └──── UDP/TCP ── Logger32
```

La web es el cliente WebSocket y el GW es el servidor. La web configura solo
el host y puerto del GW; los destinos FlexRadio y logbook se configuran en el GW.
El logbook de destino es **Logger32**, según la especificación del usuario.
Las referencias a «logbook» en este documento identifican ese destino. TCP y
UDP describen los transportes disponibles en el GW actual, sin afirmar que
ambos implementen el protocolo de integración requerido por Logger32.
El frontend guarda sus preferencias mediante `ClientStateService`, clave
`webclusterConnectorConfig`:

| Opción | Valor predeterminado | Efecto |
| --- | --- | --- |
| `enabled` | Según `WEBCLUSTER_CONNECTOR_ENABLED` | Activa la conexión |
| `host` | `127.0.0.1` | Equipo donde escucha el GW |
| `port` | `12063` | Puerto WebSocket |
| `delegateCat` | `false` | Usa el GW para CAT cuando está conectado |
| `sendQsos` | `false` | Envía los QSO guardados al logbook mediante el GW |

El endpoint construido actualmente es exclusivamente `ws://host:puerto`, sin
ruta específica, subprotocolo ni autenticación de aplicación. No intenta `wss://`;
la presencia de certificados en el GW no cambia este comportamiento. `app.py`
tampoco activa TLS en `websockets.serve`. Si se requiere WSS, habrá que coordinar
ambos extremos y comprobar las restricciones del navegador de destino.

El evento WebSocket `open` basta para marcar el conector como conectado y vaciar
la cola. El saludo `hello` también vacía la cola, pero no es una negociación de
capacidades: el frontend no comprueba `services` ni `version` para activar CAT.
Por tanto, **socket conectado no equivale a radio disponible**.

Al delegar CAT, `cat.js` desconecta el CAT serie del navegador. Al perder la
delegación puede volver a su CAT serie si estaba habilitado. Los estados CAT
recibidos del GW solo se aplican mientras la delegación está activa.

## Transporte y ciclo de conexión

- Un mensaje de aplicación es un objeto JSON en una trama de texto WebSocket.
  No es un comando FlexRadio crudo ni un datagrama binario.
- La web reintenta tras desconexión: comienza en 1 s y multiplica la espera
  por 1,7 hasta 30 s; una conexión abierta reinicia esa espera.
- Al activar manualmente el conector se utiliza una prueba inicial con límite
  de 3 s para el intento de apertura. No es un timeout para comandos CAT.
- La cola saliente conserva como máximo los 50 mensajes más recientes y se
  vacía al abrir el socket. Puede contener operaciones generadas antes de la
  reconexión; no asumir que todo comando recibido acaba de decidirse.
- Parar el conector vacía la cola y las asociaciones de QSO pendientes.
- La web no envía una suscripción CAT ni un heartbeat JSON. El GW debe publicar
  el estado por iniciativa propia. Los ping/pong de WebSocket son otra capa.
- En el módulo consultado no hay caducidad del estado CAT por falta de mensajes:
  el GW debe comunicar `alive:false` cuando pierde la radio, aunque el socket
  con la web permanezca abierto.

## GW → web: saludo y estado

Saludo que envía el GW actual al aceptar un cliente:

```json
{"topic":"connector","type":"hello","version":"dev","services":{"cat":true,"logbook":true}}
```

Estado CAT completo recomendado, compatible con el frontend:

```json
{
  "topic": "cat",
  "type": "state",
  "data": {
    "alive": true,
    "frequencyHz": 14250000,
    "band": "20m",
    "mode": "USB",
    "modeName": "USB",
    "transmitting": false,
    "source": "connector"
  }
}
```

| Campo de `data` | Tratamiento en la web |
| --- | --- |
| `alive` | Solo el booleano `true` indica radio disponible |
| `frequencyHz` | Número finito positivo en Hz; valores inválidos no borran la frecuencia anterior |
| `band` | Acepta número en metros o texto como `20m`; `70cm`, `23cm`, `13cm` se convierten a 0,7, 0,23 y 0,13 |
| `modeName` | Nombre mostrado, en mayúsculas; toma `mode` como alternativa |
| `mode` | Modo de radio utilizado para obtener la categoría del filtro |
| `transmitting` | Booleano real; otro tipo se convierte en desconocido (`null`) |
| `source` | Identificador de origen; el GW actual utiliza `connector` |

La web convierte CW/CW-REV a filtro `CW`; DATA/DATA-REV a `DIG`; y
LSB/USB/FM/AM/DV a `PHO`. Enviar `DIGU`, `DIGL` o `RTTY` directamente como
`mode` no activa el filtro digital en este código: el GW los normaliza a `DATA`.
No confundir las categorías `DIG`/`PHO` del filtro con modos de radio.

Enviar instantáneas completas: salvo la frecuencia, los campos omitidos pueden
reemplazar los anteriores por `null`, cadena vacía o `false`. Además, el frontend
no deduce la banda a partir de `frequencyHz` en este receptor.

Los cambios disparan `webcluster-connector-cat-state-change` y `cat-state-change`.
La frecuencia y el modo alimentan el visor CAT y el formulario manual de QSO;
`transmitting` controla el aspecto de transmisión. Al cerrar el socket, la web
marca `alive:false`; puede conservar valores históricos en su estado interno.

`app.py` publica cambios reales de radio y repite el estado después de cada
comprobación de enlace mediante `ping` (2 s por defecto). Solo publica
`alive:true` tras inicializar las suscripciones y disponer de frecuencia y modo
de una slice activa. Al perder el enlace reinicia el estado y publica
`alive:false`. Reintenta la conexión sin depender de que la web reconecte.

## Web → GW: comandos CAT

El flujo habitual al seleccionar una frecuencia utiliza:

```json
{"topic":"cat","type":"command","id":"webcluster-cat-EXAMPLE-1","action":"setFrequencyMode","frequencyHz":14250000,"mode":"USB"}
```

La web parte de una frecuencia en kHz y la multiplica por 1000, redondeando a
Hz. Normaliza modos con esta prioridad: texto que contenga CW → `CW`;
DIG/DATA o prefijo FT/RTTY → `DATA`; los demás → `USB` entre 5000 y 6000 kHz
inclusive o por encima de 10000 kHz, y → `LSB` en el resto.
Esta es la regla existente de la web, no una regla nueva para todas las bandas.

La API genérica `sendWebclusterConnectorCatCommand` permite otros objetos de
comando, pero el GW actual solo reconoce:

| `action` | Campos usados por `app.py` |
| --- | --- |
| `setFrequency` | `frequencyHz`, o alternativas `frequency` / `qrg` |
| `setMode` | `mode`, o alternativa `modeName` |
| `setFrequencyMode` | Frecuencia y/o modo anteriores |

Para nuevas llamadas usar siempre `frequencyHz` explícito en Hz. Las alternativas
son compatibilidad del GW, no el formato emitido por el flujo habitual de la web.
No hay aquí una acción web de PTT o transmisión.

El GW traduce a la slice activa confirmada por la radio. Si no hay una slice
activa, devuelve un error en lugar de seleccionar una arbitrariamente:

```text
C<secuencia>|slice t <slice> 14.2500
C<secuencia>|slice s <slice> mode=usb
```

Convierte `DATA` a `digu`, y normaliza los modos recibidos de Flex a los valores
esperados por la web. Los comandos TCP terminan con salto de línea.

Respuesta correlacionada con el `id` recibido:

```json
{"topic":"cat","type":"commandResult","id":"webcluster-cat-EXAMPLE-1","ok":true}
```

En error, usar `ok:false` y `message` descriptivo. La web distribuye estos
resultados a sus listeners; el módulo consultado no mantiene una tabla de
comandos pendientes ni exige un resultado antes de enviar el siguiente.
El estado visible se actualiza mediante `cat/state`, no con `commandResult`.

## Web → GW: exportación de QSO

Al guardar un QSO, si `enabled` y `sendQsos` están activos, la web genera un
registro ADIF, lo codifica como UTF-8 y después Base64:

```json
{"topic":"log","type":"add","id":"webcluster-qso-EXAMPLE-1","qsoId":"qso-example","data":"PENBTExOjU+RUEwQUE8RU9SPg=="}
```

El ejemplo `data` decodifica a `<CALL:5>EA0AA<EOR>` y solo ilustra el transporte.
Los registros reales pueden incluir QSO_DATE, TIME_ON, BAND, MODE, SUBMODE, FREQ,
CALL, DXCC, STATE, CNTY, CQZ, CONT, RST_SENT, RST_RCVD, STATION_CALLSIGN,
OPERATOR, NAME y COMMENT. Los campos vacíos se omiten. Terminan con `<EOR>`;
no se añade cabecera ADIF ni salto de línea en este constructor. FREQ es MHz;
SSB/USB/LSB/PHO se exportan como MODE SSB sin SUBMODE.

El GW decodifica `data` y transmite esos bytes al logbook configurado. No debe
tratar Base64 como cifrado ni convertir este registro en un objeto QSO propio.
`app.py` admite también `type:"send"`, aunque el flujo revisado emite `add`.

Respuesta:

```json
{"topic":"log","type":"sendResult","id":"webcluster-qso-EXAMPLE-1","ok":true,"protocol":"tcp"}
```

La web relaciona `id` con el `qsoId` guardado en memoria. Solo `ok === true`
marca ese QSO como `exported:true`; no basta con devolver `qsoId` ni abrir el
socket. Un resultado negativo o sin asociación pendiente no marca exportado.
Después elimina la asociación y emite `logbook/result`. No hay timeout ni
reenvío automático por falta de respuesta en este módulo. Las respuestas
duplicadas ya no tienen la asociación original.

El GW actual devuelve `ok:false` tras un envío UDP, explicando que no puede
confirmar recepción. En TCP devuelve `ok:true` tras escribir y drenar los bytes:
esto provoca la marca de exportado, pero **no acredita que el logbook haya
procesado o persistido el QSO**. Cualquier cambio de esa garantía requiere
definir la confirmación del programa de log, no asumirla por usar TCP.

## Otros mensajes y limitaciones que debe conocer el desarrollo

- `connector/error` con `message` es emitido por el GW para errores generales.
  El receptor lo distribuye por tema; en este módulo no hay un tratamiento
  especial que muestre automáticamente el error al usuario.
- La web reconoce `type:"superseded"`: marca el conector y CAT como no
  disponibles y emite `connector/superseded`. No cierra el socket en esa rama.
  El GW actual no emite ese mensaje ni implementa exclusividad de cliente.
- Los mensajes con `topic` se distribuyen primero por tema; `commandResult`
  y `sendResult` se vuelven a distribuir por `cat` y `log`, respectivamente.
  Un listener puede recibir dos veces el mismo resultado; no basar efectos
  irreversibles en asumir una sola notificación.

### Implementación del GW

- Una conexión FlexRadio compartida por todas las pestañas. Todas reciben el
  mismo estado; los comandos CAT se serializan. La última slice que la radio
  notifique como activa es la seleccionada. Con varios clientes SmartSDR que
  tengan slices activas simultáneas, esta política no selecciona un operador
  concreto: haría falta configurar explícitamente ese criterio.
- Estado separado por slice, sin usar `in_use=1` para seleccionarla. Eliminar o
  desactivar la slice elimina su selección; no se mezclan sus campos.
- Respuestas Flex `R<secuencia>|<código hexadecimal>|...` correlacionadas con
  cada comando. `commandResult.ok:true` significa que Flex aceptó todos los
  comandos de la operación. La frecuencia y modo publicados proceden de sus
  notificaciones, sin actualización optimista. Una operación combinada puede
  aplicarse parcialmente si el segundo comando falla; no se reintenta ni se
  revierte automáticamente. Un timeout deja el resultado desconocido.
- Reconexión automática (2 s por defecto), límites de tiempo (5 s por defecto)
  y comprobación periódica mediante `ping`. Las suscripciones deben quedar
  confirmadas antes de admitir comandos.
- Inicialización: `client program WebclusterConnector`, `sub slice all`,
  `sub tx all`, `sub radio all` y `ping`. La respuesta `10000002` a `client program` significa
  programa desconocido y se registra como aviso informativo, sin reconectar.
  Esta excepción no se aplica a comandos de frecuencia o modo. Se utiliza
  `sub tx all` para datos del transmisor y `sub radio all` para datos generales,
  incluidas las notificaciones `interlock` que permiten determinar TX/RX.
  No se envía la suscripción no documentada `sub interlock all`.
- TX se obtiene del estado de interlock o de indicadores booleanos explícitos;
  la potencia configurada y la selección de slice TX no son evidencia de emisión.
  Los estados de transición no inequívocos se publican como desconocidos.
- Recepción web y colas independientes de CAT y logbook, de hasta 50 mensajes
  cada una por cliente. El logbook no bloquea la recepción de comandos CAT.
  Una cola llena devuelve error correlacionado; no se reenvían operaciones
  automáticamente. Al cerrar una pestaña se cancelan sus tareas y operaciones
  pendientes. Una escritura ya realizada puede haber llegado al destino.
- La radio se conecta al arrancar el proceso, aunque todavía no haya navegador.
  Cerrar una pestaña no corta el enlace compartido.

La confirmación de persistencia del logbook sigue sin estar definida por su
protocolo. Se conserva la compatibilidad de `ok` de la web: TCP significa envío
por transporte (`delivery:"transport"`); UDP queda sin confirmar
(`delivery:"unconfirmed"`). No se interpreta una respuesta arbitraria como ACK.

La lógica de doble notificación de resultados y las colas de reconexión propias
del frontend son independientes de la implementación del GW.

## Ejecución y tráfico en ambos sentidos

```sh
python3 app.py
```

Muestra fecha, hora y dirección de todos los mensajes, sin truncar el contenido:
`web -> GW`, `GW -> web`, `GW -> FlexRadio`, `FlexRadio -> GW`,
`GW -> logbook TCP/UDP` y `logbook TCP/UDP -> GW`. Los bytes no UTF-8 se
representan mediante escapes. Los saltos de línea se muestran como `\n`.

Si el Python invocado no tiene `websockets`, el lanzador utiliza el intérprete
existente en `.venv/bin/python`. Para una instalación nueva, instalar primero
`requirements.txt` en el entorno Python elegido. Se requiere Python 3.11+.
La configuración predeterminada se busca junto a `app.py`, independientemente
del directorio desde el que se ejecute. `--config` permite indicar otra ruta;
`--quiet` oculta el tráfico y `--verbose` lo habilita explícitamente.
`--ws-host` permite sobrescribir la dirección de escucha WebSocket sin cambiar
el TOML. El contenedor utiliza `--ws-host 0.0.0.0` y monta la configuración en
`/config/config.toml`; Compose publica el puerto solo en el loopback del host.
El proceso atiende SIGTERM para cerrar las conexiones al detener el contenedor.
Las instrucciones de construcción y ejecución están en `README.md`.

Los destinos actuales de `config.toml` se conservan. Parámetros opcionales:

```toml
[flex]
timeout = 5
reconnect_delay = 2
ping_interval = 2

[logbook]
timeout = 5
response_timeout = 1
```

Estos campos se añaden a las secciones existentes; no duplicar sus cabeceras.
El timeout del logbook limita la operación completa. `response_timeout` limita
la espera entre bloques recibidos. Se muestran las respuestas TCP durante esa
conexión y, en UDP, la primera respuesta al mismo socket de envío. Si no llegan,
se muestra el fin del plazo. No se implementa un receptor permanente de eventos
espontáneos del logbook, ni un protocolo de sincronización de QSO de vuelta a
la web. Para eso falta concretar la interfaz de Logger32 utilizada, su formato
de mensajes y sus confirmaciones; el programa de destino ya está identificado.

## Validación

Por petición del usuario no se añaden ni ejecutan pruebas, comprobaciones
automáticas ni validaciones funcionales. La validación queda a su cargo.

Referencias oficiales consultadas para respuestas correlacionadas y TX/RX:
[SmartSDR TCP/IP API](https://github.com/flexradio/smartsdr-api-docs/wiki/SmartSDR-TCPIP-API)
y [estados de interlock](https://github.com/flexradio/smartsdr-api-docs/wiki/TCPIP-xmit).
Para inicialización y el aviso `10000002`, véanse
[client program](https://github.com/flexradio/smartsdr-api-docs/wiki/TCPIP-client#program)
y [suscripciones](https://github.com/flexradio/smartsdr-api-docs/wiki/TCPIP-sub).
