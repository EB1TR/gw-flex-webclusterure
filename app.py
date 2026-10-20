#!/usr/bin/env python3
"""Gateway WebClusterURE / FlexRadio y transporte ADIF al logbook."""
import argparse
import asyncio
import base64
import contextlib
import json
import math
import os
import sys
import re
import signal
import socket
import tomllib
from datetime import datetime
from pathlib import Path

try:
    import websockets
except ImportError:
    local_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
    if __name__ == "__main__" and local_python.exists() and Path(sys.prefix) != local_python.parent.parent:
        os.execv(str(local_python), [str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit("Falta websockets. Instálalo con: python3 -m pip install -r requirements.txt")

DEFAULT_CONFIG = {
    "websocket": {"host": "127.0.0.1", "port": 12063},
    "flex": {"host": "192.168.88.52", "port": 4992,
             "timeout": 5, "reconnect_delay": 2, "ping_interval": 2},
    "logbook": {"protocol": "udp", "host": "127.0.0.1", "port": 2237,
                "timeout": 5, "response_timeout": 1},
    "debug": {"verbose": False, "level": 2},
}


def positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Se esperaba un número finito positivo")
    return number


class Config:
    def __init__(self, data):
        for section, prefix in (("websocket", "ws"), ("flex", "flex"), ("logbook", "logbook")):
            setattr(self, prefix + "_host", str(data[section]["host"]))
            port = int(data[section]["port"])
            if not 1 <= port <= 65535:
                raise ValueError(f"Puerto inválido en {section}")
            setattr(self, prefix + "_port", port)
        self.logbook_protocol = str(data["logbook"]["protocol"]).lower()
        if self.logbook_protocol not in ("udp", "tcp"):
            raise ValueError("logbook.protocol debe ser udp o tcp")
        self.flex_timeout = positive_number(data["flex"]["timeout"])
        self.reconnect_delay = positive_number(data["flex"]["reconnect_delay"])
        self.ping_interval = positive_number(data["flex"]["ping_interval"])
        self.logbook_timeout = positive_number(data["logbook"]["timeout"])
        self.response_timeout = positive_number(data["logbook"]["response_timeout"])
        self.verbose = bool(data["debug"]["verbose"])
        self.debug_level = int(data["debug"]["level"])


def load_config(path):
    data = {key: value.copy() for key, value in DEFAULT_CONFIG.items()}
    with Path(path).open("rb") as stream:
        for key, value in tomllib.load(stream).items():
            if key in data and isinstance(value, dict):
                data[key].update(value)
    return Config(data)


APP_CONFIG = Config(DEFAULT_CONFIG)


def report(message):
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


def trace(direction, payload, level=1):
    if not APP_CONFIG.verbose or APP_CONFIG.debug_level < level:
        return
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="backslashreplace")
    # repr mantiene una línea por evento sin ocultar los límites del protocolo.
    report(f"[{direction}] {payload!r}")


def frequency_hz_to_band(frequency_hz):
    if not frequency_hz:
        return None
    band_ranges = (
        (1800000, 2000000, "160m"),
        (3500000, 4000000, "80m"),
        (5000000, 5500000, "60m"),
        (7000000, 7300000, "40m"),
        (10100000, 10150000, "30m"),
        (14000000, 14350000, "20m"),
        (18068000, 18168000, "17m"),
        (21000000, 21450000, "15m"),
        (24890000, 24990000, "12m"),
        (28000000, 29700000, "10m"),
        (50000000, 54000000, "6m"),
        (70000000, 71000000, "4m"),
        (144000000, 148000000, "2m"),
        (430000000, 440000000, "70cm"),
        (1240000000, 1300000000, "23cm"),
        (2300000000, 2450000000, "13cm"),
    )
    for lower, upper, band in band_ranges:
        if lower <= frequency_hz <= upper:
            return band
    return None


def flex_mode_to_webcluster_mode(mode):
    mode = str(mode or "").strip().upper()
    if mode in ("CW", "CW-REV"):
        return "CW"
    if mode in ("NFM", "DFM"):
        return "FM"
    if mode == "SAM":
        return "AM"
    if mode in ("LSB", "USB", "FM", "AM", "DV"):
        return mode
    if mode in ("DIGU", "DIGL", "RTTY", "DATA", "DATA-REV"):
        return "DATA"
    return mode or None


def parse_key_values(text):
    values = {}
    for part in str(text or "").split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()
    return values



class FlexCatState:
    def __init__(self):
        self.slices = {}
        self.active_slice_id = None
        self.transmitting = None

    def to_payload(self, alive=False):
        current = self.slices.get(self.active_slice_id, {})
        frequency = current.get("frequencyHz")
        mode = current.get("mode")
        return {"topic": "cat", "type": "state", "data": {
            "alive": bool(alive and frequency and mode),
            "frequencyHz": frequency, "band": frequency_hz_to_band(frequency),
            "mode": mode, "modeName": mode, "transmitting": self.transmitting,
            "source": "connector"}}

    def update(self, line):
        match = re.match(r"^S[^|]*\|slice\s+(\d+)\s+(.+)$", line)
        if match:
            slice_id, text = match.groups()
            values = parse_key_values(text)
            if values.get("in_use") == "0" or text.strip() == "removed":
                self.slices.pop(slice_id, None)
            else:
                current = self.slices.setdefault(slice_id, {})
                if "active" in values:
                    current["active"] = values["active"] == "1"
                    if current["active"]:
                        for other_id, other in self.slices.items():
                            if other_id != slice_id:
                                other["active"] = False
                if "RF_frequency" in values:
                    try:
                        current["frequencyHz"] = round(positive_number(values["RF_frequency"]) * 1000000)
                    except (ValueError, OverflowError):
                        pass
                if "mode" in values:
                    current["mode"] = flex_mode_to_webcluster_mode(values["mode"])
            active = [key for key, value in self.slices.items() if value.get("active")]
            # Sin slice activa no se dirige un comando a una slice arbitraria.
            self.active_slice_id = active[0] if active else None
            return True
        match = re.match(r"^S[^|]*\|(interlock|transmit|radio)\s+(.+)$", line)
        if not match:
            return False
        topic, text = match.groups()
        values = parse_key_values(text)
        if topic == "interlock" and "state" in values:
            state = values["state"].upper()
            self.transmitting = True if state == "TRANSMITTING" else (
                False if state in {"RECEIVE", "READY", "NOT_READY", "PTT_REQUESTED",
                                  "TX_FAULT", "TIMEOUT", "STUCK_INPUT"} else None)
            return True
        for key in ("mox", "ptt", "transmitting"):
            if values.get(key) in ("0", "1"):
                self.transmitting = values[key] == "1"
                return True
        # rf_power es una potencia configurada, no evidencia de TX.
        return False


async def close_writer(writer):
    if writer is not None:
        writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(writer.wait_closed(), 1)


class FlexRadio:
    def __init__(self, publish):
        self.publish = publish
        self.state = FlexCatState()
        self.writer = None
        self.pending = {}
        self.sequence = 0
        self.ready = False
        self.command_lock = asyncio.Lock()

    def payload(self):
        return self.state.to_payload(self.ready)

    async def command(self, text, informational_codes=()):
        writer = self.writer
        if writer is None:
            raise ConnectionError("FlexRadio desconectada")
        self.sequence += 1
        sequence = str(self.sequence)
        future = asyncio.get_running_loop().create_future()
        self.pending[sequence] = future
        try:
            async with asyncio.timeout(APP_CONFIG.flex_timeout):
                raw = f"C{sequence}|{text}\n"
                trace("GW -> FlexRadio", raw)
                writer.write(raw.encode("utf-8"))
                await writer.drain()
                code, response = await future
                response_code = int(code, 16)
                if response_code in informational_codes:
                    report(f"FlexRadio: aviso informativo {code}: {response}; se continúa la conexión")
                elif response_code != 0:
                    raise ValueError(f"FlexRadio rechazó {text!r}: {code} {response}")
                return response
        except TimeoutError:
            raise TimeoutError(f"FlexRadio no confirmó {text!r}; resultado desconocido") from None
        finally:
            self.pending.pop(sequence, None)

    async def read(self, reader):
        while True:
            raw = await reader.readline()
            if not raw:
                raise ConnectionError("FlexRadio cerró la conexión")
            line = raw.decode("utf-8", errors="replace").strip()
            trace("FlexRadio -> GW", line)
            match = re.match(r"^R(\d+)\|([0-9a-fA-F]+)\|(.*)$", line)
            if match:
                sequence, code, response = match.groups()
                future = self.pending.get(sequence)
                if future is not None and not future.done():
                    future.set_result((code, response))
            elif self.state.update(line):
                await self.publish(self.payload())

    async def run(self):
        while True:
            reader_task = None
            writer = None
            try:
                self.state = FlexCatState()
                report(f"Conectando FlexRadio {APP_CONFIG.flex_host}:{APP_CONFIG.flex_port}")
                reader, writer = await asyncio.wait_for(asyncio.open_connection(
                    APP_CONFIG.flex_host, APP_CONFIG.flex_port), APP_CONFIG.flex_timeout)
                self.writer = writer
                reader_task = asyncio.create_task(self.read(reader))
                # Si el lector termina, despertar inmediatamente los comandos pendientes.
                reader_task.add_done_callback(self.reader_finished)
                # 10000002 identifica un programa desconocido; no es un fallo CAT.
                # Solo se admite para esta identificación, nunca para sintonía/modo.
                await self.command("client program WebclusterConnector", informational_codes=(0x10000002,))
                for command in ("sub slice all", "sub tx all", "sub radio all"):
                    await self.command(command)
                await self.command("ping")
                self.ready = True
                report("FlexRadio conectada; suscripciones confirmadas")
                await self.publish(self.payload())
                while True:
                    done, _ = await asyncio.wait({reader_task}, timeout=APP_CONFIG.ping_interval)
                    if done:
                        await reader_task
                    await self.command("ping")
                    await self.publish(self.payload())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report(f"FlexRadio: {exc}. Se reintentará la conexión.")
            finally:
                self.ready = False
                self.writer = None
                if reader_task:
                    reader_task.cancel()
                    await asyncio.gather(reader_task, return_exceptions=True)
                self.fail_pending()
                await close_writer(writer)
                self.state = FlexCatState()
                await self.publish(self.payload())
            await asyncio.sleep(APP_CONFIG.reconnect_delay)

    def reader_finished(self, task):
        self.ready = False
        self.fail_pending()

    def fail_pending(self):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Se perdió el enlace FlexRadio"))

    async def execute(self, message):
        async with self.command_lock:
            if not self.ready:
                raise ConnectionError("Radio no disponible")
            slice_id = self.state.active_slice_id
            if slice_id is None:
                raise ValueError("No hay una slice activa confirmada por la radio")
            action = message.get("action")
            if action not in {"setFrequency", "setMode", "setFrequencyMode"}:
                raise ValueError("Acción CAT no reconocida")
            commands = []
            frequency = message.get("frequencyHz", message.get("frequency", message.get("qrg")))
            mode = message.get("mode", message.get("modeName"))
            if action == "setFrequency" and frequency is None:
                raise ValueError("Falta frequencyHz")
            if action == "setMode" and mode is None:
                raise ValueError("Falta mode")
            if frequency is not None and action != "setMode":
                frequency = positive_number(frequency)
                if "frequencyHz" in message:
                    frequency /= 1000000
                elif frequency > 1000000:
                    frequency /= 1000000
                elif frequency > 1000:
                    frequency /= 1000
                commands.append(f"slice t {slice_id} {frequency:.6f}")
            if mode is not None and action != "setFrequency":
                mode = str(mode).strip().upper()
                mode = {"PHO": "USB", "PHONE": "USB", "SSB": "USB", "DIG": "DIGU", "DATA": "DIGU"}.get(mode, mode)
                if mode not in {"LSB", "USB", "AM", "SAM", "CW", "DIGL", "DIGU", "FM", "NFM", "DFM", "RTTY", "DV"}:
                    raise ValueError("Modo CAT no admitido")
                commands.append(f"slice s {slice_id} mode={mode.lower()}")
            if not commands:
                raise ValueError("Comando CAT vacío")
            for command in commands:
                await self.command(command)
            # El estado se publica únicamente al recibir notificaciones reales.


async def send_logbook(message):
    result = {"topic": "log", "type": "sendResult", "id": message.get("id", ""),
              "ok": False, "protocol": APP_CONFIG.logbook_protocol}
    try:
        raw = base64.b64decode(message.get("data", ""), validate=True)
        if not raw:
            raise ValueError("Registro vacío")
        protocol = APP_CONFIG.logbook_protocol
        async with asyncio.timeout(APP_CONFIG.logbook_timeout):
            if protocol == "tcp":
                reader, writer = await asyncio.open_connection(APP_CONFIG.logbook_host, APP_CONFIG.logbook_port)
                try:
                    trace("GW -> logbook TCP", raw)
                    writer.write(raw)
                    await writer.drain()
                    # Captura respuestas sin exigir un ACK que el protocolo ADIF no define.
                    try:
                        while True:
                            response = await asyncio.wait_for(reader.read(4096), APP_CONFIG.response_timeout)
                            if not response:
                                break
                            trace("logbook TCP -> GW", response)
                    except TimeoutError:
                        trace("logbook TCP -> GW", "Sin más respuesta dentro del plazo")
                    result.update(ok=True, delivery="transport", message="Bytes enviados por TCP; registro en el logbook no confirmado")
                finally:
                    await close_writer(writer)
            else:
                loop = asyncio.get_running_loop()
                addresses = await loop.getaddrinfo(APP_CONFIG.logbook_host, APP_CONFIG.logbook_port, type=socket.SOCK_DGRAM)
                family, kind, proto, _, target = addresses[0]
                with socket.socket(family, kind, proto) as sock:
                    sock.setblocking(False)
                    await loop.sock_connect(sock, target)
                    trace("GW -> logbook UDP", raw)
                    await loop.sock_sendall(sock, raw)
                    try:
                        response = await asyncio.wait_for(loop.sock_recv(sock, 65535), APP_CONFIG.response_timeout)
                        trace("logbook UDP -> GW", response)
                    except TimeoutError:
                        trace("logbook UDP -> GW", "Sin respuesta dentro del plazo")
                result.update(delivery="unconfirmed", message="Datagrama enviado; recepción y registro no confirmados")
    except Exception as exc:
        result["message"] = str(exc) or type(exc).__name__
    return result


class Gateway:
    def __init__(self):
        self.clients = set()
        self.radio = FlexRadio(self.broadcast)

    async def send(self, websocket, message):
        raw = json.dumps(message, ensure_ascii=False)
        trace("GW -> web", raw, level=2)
        await asyncio.wait_for(websocket.send(raw), 3)

    async def broadcast(self, message):
        async def deliver(websocket):
            try:
                await self.send(websocket, message)
            except Exception:
                self.clients.discard(websocket)
                with contextlib.suppress(Exception):
                    await websocket.close()
        await asyncio.gather(*(deliver(client) for client in tuple(self.clients)))

    async def worker(self, websocket, queue, topic):
        while True:
            message = await queue.get()
            try:
                if topic == "log":
                    result = await send_logbook(message)
                else:
                    result = {"topic": "cat", "type": "commandResult", "id": message.get("id", ""), "ok": False}
                    try:
                        await self.radio.execute(message)
                        result["ok"] = True
                        result["message"] = "Comandos aceptados por FlexRadio"
                    except Exception as exc:
                        result["message"] = str(exc) or type(exc).__name__
                if not result["ok"]:
                    report(f"{'Logger32' if topic == 'log' else 'CAT'}: {result.get('message', 'Operación no confirmada')}")
                await self.send(websocket, result)
            finally:
                queue.task_done()

    async def handle_client(self, websocket):
        report(f"Web conectada: {websocket.remote_address}")
        queues = {topic: asyncio.Queue(maxsize=50) for topic in ("cat", "log")}
        workers = [asyncio.create_task(self.worker(websocket, queue, topic)) for topic, queue in queues.items()]
        receive_task = None
        try:
            await self.send(websocket, {"topic": "connector", "type": "hello", "version": "1",
                                        "services": {"cat": True, "logbook": True}})
            self.clients.add(websocket)
            await self.send(websocket, self.radio.payload())
            receive_task = asyncio.create_task(self.receive(websocket, queues))
            done, _ = await asyncio.wait([receive_task, *workers], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            tasks = workers + ([receive_task] if receive_task else [])
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            report("Web desconectada; tareas del cliente cerradas")

    async def receive(self, websocket, queues):
        async for payload in websocket:
            trace("web -> GW", payload, level=2)
            try:
                if not isinstance(payload, str):
                    raise ValueError("Se requiere una trama de texto JSON")
                message = json.loads(payload)
                if not isinstance(message, dict):
                    raise ValueError("El mensaje JSON debe ser un objeto")
                topic = message.get("topic")
                if topic == "cat" and message.get("type") == "command":
                    queue = queues["cat"]
                elif topic == "log" and message.get("type") in ("add", "send"):
                    queue = queues["log"]
                else:
                    raise ValueError("Tema o tipo de mensaje no reconocido")
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    report(f"Cola {topic} llena; operación no enviada")
                    await self.send(websocket, {"topic": topic, "type": "commandResult" if topic == "cat" else "sendResult",
                                                "id": message.get("id", ""), "ok": False, "message": "Cola llena; operación no enviada"})
            except (ValueError, TypeError) as exc:
                report(f"Mensaje web rechazado: {exc}")
                await self.send(websocket, {"topic": "connector", "type": "error", "message": str(exc)})


async def main():
    gateway = Gateway()
    report(f"WebSocket: ws://{APP_CONFIG.ws_host}:{APP_CONFIG.ws_port}")
    report(f"Logbook: {APP_CONFIG.logbook_protocol.upper()} {APP_CONFIG.logbook_host}:{APP_CONFIG.logbook_port}")
    radio_task = None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    # Docker envía SIGTERM al detener el contenedor.
    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, stopped.set)
    try:
        async with websockets.serve(gateway.handle_client, APP_CONFIG.ws_host, APP_CONFIG.ws_port):
            radio_task = asyncio.create_task(gateway.radio.run())
            await stopped.wait()
    finally:
        if radio_task:
            radio_task.cancel()
            await asyncio.gather(radio_task, return_exceptions=True)
        with contextlib.suppress(NotImplementedError):
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GW WebClusterURE ↔ FlexRadio y logbook")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.toml")), help="ruta al TOML de configuración")
    parser.add_argument("--ws-host", help="dirección de escucha WebSocket; sobrescribe el TOML")
    traffic = parser.add_mutually_exclusive_group()
    traffic.add_argument("--quiet", action="store_true", help="ocultar el intercambio; mantener conexiones y errores")
    traffic.add_argument("--verbose", action="store_true", help="mostrar todo el intercambio para diagnóstico")
    args = parser.parse_args()
    try:
        APP_CONFIG = load_config(args.config)
        if args.ws_host is not None:
            APP_CONFIG.ws_host = args.ws_host
        if args.quiet:
            APP_CONFIG.verbose = False
        elif args.verbose:
            APP_CONFIG.verbose = True
            APP_CONFIG.debug_level = 2
        asyncio.run(main())
    except KeyboardInterrupt:
        report("GW detenido")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"No se pudo iniciar el GW: {exc}")
