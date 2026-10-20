# Instrucciones para agentes

## Proyecto

Conector Python entre Webcluster (WebSocket), FlexRadio (TCP) y un libro de
guardia Logger32 (transporte implementado UDP o TCP). El código de la aplicación está en `app.py`; no hay un
frontend en este directorio.

El contrato con el frontend está documentado en `PROTOCOLO_WEBCLUSTER.md`.
Leerlo antes de modificar mensajes WebSocket, estado CAT o exportación al
logbook. Se obtuvo mediante una lectura puntual del frontend el 20 de octubre
de 2026; usar esta referencia local sin volver a consultar el repositorio del
frontend salvo petición del usuario. Distingue comportamiento observado,
limitaciones del GW y mejoras pendientes; no asumir que estas últimas ya están
implementadas.

## Estructura y entorno

- `app.py`: configuración, conversión de frecuencias y modos, estado CAT,
  comandos FlexRadio, envío al logbook y servidor WebSocket asíncrono.
- `config.toml`: configuración local de los servicios y del diagnóstico.
- `requirements.txt`: dependencia WebSocket para instalaciones nuevas.
- `Dockerfile`, `.dockerignore` y `compose.yaml`: contenedor basado en Python
  Alpine, con configuración externa y un único proceso de aplicación.
- `.venv/`: entorno local existente; no editar sus archivos ni incluirlo en
  entregas.
- Se requiere Python 3.11 o posterior por el uso de `tomllib`, y la dependencia
  externa `websockets`, declarada en `requirements.txt`.
- Repositorio público: `EB1TR/gw-flex-webclusterure`, con rama principal
  `main`. No incluir `config.toml`, certificados, claves ni archivos de entorno
  en commits. Usar `config.example.toml` como plantilla de configuración.

## Ejecución

Desde la raíz del proyecto:

```sh
python3 app.py
```

El comando mantiene el servidor en ejecución. Al arrancar, el conector intenta
abrir una conexión con la radio configurada, aunque no haya clientes web.
No enviar comandos a la radio ni registros al logbook real sin que forme parte
de la petición del usuario. La validación la realiza personalmente el usuario.

## Criterios de modificación

- No leer archivos de entorno (`.env`, `.env.*` y equivalentes), contraseñas
  ni archivos que contengan credenciales. No buscar, mostrar ni copiar estos
  secretos; utilizar valores ficticios en los ejemplos.
- Mantener el estilo existente: cuatro espacios, funciones en `snake_case`,
  clases en `PascalCase` y operaciones de red con `asyncio`.
- Mantener los cambios centrados en la petición; no introducir frameworks ni
  reorganizar toda la aplicación para una corrección puntual.
- Conservar la compatibilidad de los mensajes JSON: temas `connector`, `cat` y
  `log`, tipos de mensaje, identificadores y campos de respuesta existentes.
- El estado CAT publica `frequencyHz` en Hz; FlexRadio utiliza MHz en sus
  comandos. Preservar las conversiones y los alias de modos existentes.
- En las notificaciones de slice, `tx=1` selecciona el slice de transmisión;
  no demuestra que la radio esté transmitiendo en ese momento.
- Conservar la distinción entre enviar un datagrama UDP y confirmar su
  recepción. Tampoco presentar una escritura TCP como confirmación de que el
  libro de guardia ha procesado el registro.
- El logbook de destino es Logger32. No asumir que el envío de ADIF crudo o
  una respuesta de transporte equivalen a su protocolo de integración o a
  confirmación de registro; documentar por separado lo pendiente de concretar.
- Respetar el cierre de conexiones, las tareas asíncronas y las notificaciones
  `alive` al modificar el ciclo de vida de las conexiones.
- `APP_CONFIG` contiene la configuración del proceso. El estado CAT pertenece
  a la conexión compartida con FlexRadio y se reinicia al perder el enlace.
- No sustituir direcciones, puertos ni preferencias de `config.toml` por valores
  del entorno de pruebas. Mantener la escucha local predeterminada.
- Mantener los mensajes al usuario y la documentación en español.
- Mantener ligera la imagen: no incluir configuración local, entornos Python,
  cachés ni herramientas de desarrollo. El puerto publicado en Compose debe
  coincidir con el puerto WebSocket configurado. La escucha `0.0.0.0` se limita
  al arranque del contenedor mediante `--ws-host`.

## Validación

- No añadir ni ejecutar pruebas de ningún tipo, comprobaciones automáticas,
  compilaciones de prueba ni validaciones funcionales. El usuario realiza
  personalmente toda la validación.
- Esta regla también se aplica a servicios simulados y dobles de red.
- No iniciar la aplicación para validarla salvo petición expresa del usuario.
- Al entregar, describir los cambios e indicar que la validación queda a cargo
  del usuario.
