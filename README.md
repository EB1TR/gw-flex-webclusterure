# GW FlexRadio para WebClusterURE

Gateway Python que conecta el frontend WebClusterURE por WebSocket con una
radio FlexRadio por TCP y reenvía registros ADIF al logbook Logger32.
La implementación actual permite seleccionar transporte TCP o UDP; la
compatibilidad del intercambio concreto con Logger32 requiere validación manual.

## Instalación

Requiere Python 3.11 o posterior.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.toml config.toml
```

Editar `config.toml` para indicar las direcciones de la radio y el logbook.
La configuración local, los certificados y las claves quedan excluidos de Git.

## Uso

```sh
python3 app.py
```

Si el intérprete no dispone de `websockets`, la aplicación utiliza el entorno
local `.venv` cuando existe. Por defecto registra conexiones, reconexiones y
errores, sin mostrar los mensajes intercambiados. `--config ruta.toml` permite
seleccionar otro archivo de configuración.

Para diagnosticar el intercambio en ambos sentidos con la web, FlexRadio y
Logger32:

```sh
python3 app.py --verbose
```

Sin opciones de tráfico se respeta `[debug].verbose` y `[debug].level` del TOML.
`--quiet` fuerza la ocultación del intercambio; `--verbose` lo activa completo
con nivel 2. Las dos opciones son excluyentes. Ninguna oculta los avisos de
conexión ni los errores de operaciones.

En WebClusterURE, configurar el conector hacia `ws://127.0.0.1:12063` cuando
el navegador y el GW están en el mismo equipo. Activar la delegación CAT o el
envío de QSO según se necesite. El GW se conecta a la radio al arrancar y
comparte ese enlace entre los clientes web.

El envío TCP al logbook acredita la escritura de bytes, no que el programa haya
guardado el QSO. UDP se informa como envío sin confirmación. Las respuestas del
logbook se muestran en modo diagnóstico durante la ventana de recepción configurada.

## Contenedor ligero

La imagen utiliza Python 3.14 sobre Alpine. Incluye únicamente `app.py` y las
dependencias de `websockets` sobre esa base; la instalación se hace en una etapa
separada, sin añadir compiladores ni guardar cachés de paquetes. La configuración,
el entorno local y la documentación no entran en el contexto de construcción.
El tamaño final depende de la arquitectura y de las versiones descargadas;
no se ha medido.

Crear `config.toml` desde la plantilla si todavía no existe y ajustar los
destinos antes de arrancar. No sobrescribir una configuración local existente.
Docker Compose monta ese archivo en modo de solo lectura:

```sh
docker compose up -d --build
docker compose logs -f gateway
```

Para detenerlo:

```sh
docker compose down
```

Compose utiliza `command: ["--quiet"]` para el funcionamiento normal. Para
diagnosticar, sustituirlo temporalmente por `command: ["--verbose"]` y recrear
solo el servicio con `docker compose up -d --no-deps gateway`. Después restaurar
`--quiet` y recrearlo de nuevo. En modo normal no se imprimen los `ping`, sus
respuestas ni los estados CAT periódicos; se siguen enviando por la red.
El proceso recibe SIGTERM para cerrar sus conexiones al detener el contenedor.
Los registros de Docker se rotan en dos archivos de hasta 5 MB cada uno.

### Red y configuración

- En `[flex]`, usar la IP de la radio accesible desde el equipo que ejecuta Docker.
- En `[logbook]`, usar la IP del equipo con el logbook. Si está en el propio
  host Docker, puede usarse `host.docker.internal`; el servicio debe aceptar
  conexiones desde la red de Docker. `127.0.0.1` dentro del contenedor apunta
  al propio contenedor.
- Mantener `[websocket].port = 12063` para el mapeo de puertos incluido.
  El contenedor usa `--ws-host 0.0.0.0` para aceptar la conexión desde Docker,
  sin modificar el TOML ni la escucha de la ejecución directa con Python.
- Compose publica el puerto solo en `127.0.0.1` del host. La web abierta en ese
  equipo utiliza `ws://127.0.0.1:12063`. Para un navegador en otro equipo,
  cambiar la dirección de publicación en `compose.yaml` por la IP LAN del host
  y configurar esa misma IP en el frontend.

El contenedor corre con UID/GID `10001:10001`, sistema de archivos de solo
lectura y sin capacidades adicionales. El TOML montado debe ser legible por ese
usuario. Compose establece límites de 64 MiB de memoria, 0,5 CPU y 32 procesos;
son límites configurables, no una medición del consumo real. No se añade un
servidor web auxiliar ni un proceso periódico de comprobación.

También puede utilizarse Docker sin Compose:

```sh
docker build -t gw-flex-webclusterure:local .
docker run --rm --name gw-flex-webclusterure \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 64m --cpus 0.5 --pids-limit 32 \
  --add-host host.docker.internal:host-gateway \
  -p 127.0.0.1:12063:12063 \
  --mount type=bind,src="$(pwd)/config.toml",dst=/config/config.toml,readonly \
  gw-flex-webclusterure:local
```

Para mostrar el tráfico, añadir `--verbose` al final del comando `docker run`;
para forzar el modo normal aunque el TOML habilite diagnóstico, añadir `--quiet`.
La construcción y el funcionamiento del contenedor quedan pendientes de la
validación manual del usuario.

## Documentación y desarrollo

- [Contrato con WebClusterURE](PROTOCOLO_WEBCLUSTER.md): mensajes, unidades,
  suscripciones, funcionamiento y limitaciones.
- [Instrucciones de trabajo](AGENTS.md): alcance y reglas del proyecto.

La validación funcional la realiza personalmente el usuario. No se añaden ni
ejecutan pruebas automatizadas.

## Sincronización con GitHub

Repositorio público: [EB1TR/gw-flex-webclusterure](https://github.com/EB1TR/gw-flex-webclusterure).
El remoto local `origin` apunta a ese repositorio.

Los cambios se sincronizan mediante commits y push; no se publican
automáticamente al editar un archivo. Para recuperar cambios remotos, utilizar
`git pull`. Para enviar los propios, seleccionar los archivos, crear un commit
y ejecutar `git push`.
