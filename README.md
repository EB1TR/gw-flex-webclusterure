# GW FlexRadio para WebClusterURE

Gateway Python que conecta el frontend WebClusterURE por WebSocket con una
radio FlexRadio por TCP y reenvía registros ADIF a un logbook por TCP o UDP.

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
local `.venv` cuando existe. Muestra el tráfico en ambos sentidos con la web,
la radio y el logbook. `--quiet` permite ocultarlo y `--config ruta.toml`
seleccionar otro archivo de configuración.

En WebClusterURE, configurar el conector hacia `ws://127.0.0.1:12063` cuando
el navegador y el GW están en el mismo equipo. Activar la delegación CAT o el
envío de QSO según se necesite. El GW se conecta a la radio al arrancar y
comparte ese enlace entre los clientes web.

El envío TCP al logbook acredita la escritura de bytes, no que el programa haya
guardado el QSO. UDP se informa como envío sin confirmación. Las respuestas del
logbook se muestran durante la ventana de recepción configurada.

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
