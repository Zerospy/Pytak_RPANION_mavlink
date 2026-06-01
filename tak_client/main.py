import asyncio
import logging
import math
import socket
from configparser import SectionProxy
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

import pytak
from pytak.asyncio_dgram import from_socket
from pymavlink import mavutil

from .config import load_config
from .cot import build_geochat_event, build_position_event, build_position_event_from_values


LOGGER = logging.getLogger(__name__)


class PositionState:
    def __init__(self, config: SectionProxy):
        self.lat = float(config.get("TAK_LAT", "0"))
        self.lon = float(config.get("TAK_LON", "0"))
        self.hae = float(config.get("TAK_HAE", "0"))
        self.updated = asyncio.Event()

    def update(self, lat: float, lon: float, hae: float) -> None:
        self.lat = lat
        self.lon = lon
        self.hae = hae
        self.updated.set()

    def format_position(self) -> str:
        return f"{self.lat:.7f}, {self.lon:.7f}, hae={self.hae:.1f}m"


def bearing_between_points(
    previous_lat: float,
    previous_lon: float,
    current_lat: float,
    current_lon: float,
) -> float:
    previous_lat_rad = math.radians(previous_lat)
    current_lat_rad = math.radians(current_lat)
    delta_lon_rad = math.radians(current_lon - previous_lon)

    x = math.sin(delta_lon_rad) * math.cos(current_lat_rad)
    y = (
        math.cos(previous_lat_rad) * math.sin(current_lat_rad)
        - math.sin(previous_lat_rad)
        * math.cos(current_lat_rad)
        * math.cos(delta_lon_rad)
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def course_speed_from_global_position(msg) -> tuple[float | None, float | None]:
    vx = getattr(msg, "vx", None)
    vy = getattr(msg, "vy", None)
    if vx is None or vy is None:
        return None, None

    north_mps = vx / 100.0
    east_mps = vy / 100.0
    speed_mps = math.hypot(north_mps, east_mps)
    if speed_mps < 0.05:
        return None, speed_mps

    course = (math.degrees(math.atan2(east_mps, north_mps)) + 360.0) % 360.0
    return course, speed_mps


def extract_cot_xml(data: bytes) -> bytes | None:
    start = data.find(b"<event")
    end = data.find(b"</event>")
    if start == -1 or end == -1:
        return None
    return data[start : end + len(b"</event>")]


def udp_write_only_url(raw_url: str) -> str:
    cot_url = urlparse(raw_url)
    if "udp" not in cot_url.scheme or "+wo" in cot_url.scheme:
        return raw_url

    return urlunparse(cot_url._replace(scheme=f"{cot_url.scheme}+wo"))


async def create_udp_bind_all_reader(raw_url: str):
    cot_url = urlparse(raw_url)
    if "udp" not in cot_url.scheme or cot_url.port is None:
        return None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", cot_url.port))
    LOGGER.info("Listening for UDP CoT on 0.0.0.0:%s", cot_url.port)
    return await from_socket(sock)


class PositionWorker(pytak.QueueWorker):
    """Genera una posicion simple recurrente."""

    def __init__(self, tx_queue, config: SectionProxy, position_state: PositionState):
        super().__init__(tx_queue, config)
        self.interval = int(config.get("TAK_INTERVAL", "10"))
        self.position_state = position_state

    async def run(self) -> None:
        while True:
            self.position_state.update(
                float(self.config.get("TAK_LAT", "0")),
                float(self.config.get("TAK_LON", "0")),
                float(self.config.get("TAK_HAE", "0")),
            )
            event = build_position_event(self.config)
            await self.put_queue(event)
            LOGGER.info("Sent CoT position event uid=%s", self.config.get("TAK_UID"))
            await asyncio.sleep(self.interval)


class ChatAnnounceWorker(pytak.QueueWorker):
    """Envia un GeoChat inicial para que otros clientes vean actividad de chat."""

    def __init__(self, tx_queue, config: SectionProxy, position_state: PositionState):
        super().__init__(tx_queue, config)
        self.position_state = position_state

    async def run(self) -> None:
        message = self.config.get("TAK_CHAT_ANNOUNCE", "").strip()
        if message:
            timeout = float(self.config.get("TAK_CHAT_ANNOUNCE_POSITION_TIMEOUT", "10"))
            try:
                await asyncio.wait_for(self.position_state.updated.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                LOGGER.warning("Sending GeoChat announce with fallback configured position")

            message = f"{message} | Posicion: {self.position_state.format_position()}"
            event = build_geochat_event(self.config, message)
            await self.put_queue(event)
            LOGGER.info(
                "Sent GeoChat announce room=%s",
                self.config.get("TAK_CHAT_ROOM", "All Chat Rooms"),
            )

        while True:
            await asyncio.sleep(3600)


class ChatReceiveWorker(pytak.Worker):
    """Lee GeoChat entrante desde la cola RX y lo registra en logs."""

    def __init__(self, rx_queue, tx_queue, config: SectionProxy):
        super().__init__(rx_queue, config)
        self.tx_queue = tx_queue

    async def send_status_response(self, room: str | None = None) -> None:
        response = self.config.get(
            "TAK_CHAT_STATUS_RESPONSE",
            "Estado: online, publicando posicion CoT.",
        )
        chat_room = room or self.config.get("TAK_CHAT_ROOM", "All Chat Rooms")
        event = build_geochat_event(self.config, response, room=chat_room)
        await self.tx_queue.put(event)
        LOGGER.info("Sent GeoChat status response room=%s", chat_room)

    async def handle_raw_status_command(self, data: bytes) -> bool:
        command = self.config.get("TAK_CHAT_STATUS_COMMAND", "Estado").strip()
        if not command:
            return False

        if command.casefold() not in data.decode(errors="ignore").casefold():
            return False

        LOGGER.info("Received raw chat status command=%s", command)
        await self.send_status_response()
        return True

    async def handle_data(self, data: bytes) -> None:
        debug_rx = self.config.getboolean("TAK_CHAT_DEBUG_RX", fallback=False)
        cot_xml = extract_cot_xml(data)
        if cot_xml is None:
            if debug_rx:
                LOGGER.info("RX payload without CoT XML: %r", data[:200])
            await self.handle_raw_status_command(data)
            return

        try:
            event = ET.fromstring(cot_xml)
        except ET.ParseError:
            LOGGER.warning("Could not parse RX CoT XML: %r", cot_xml[:200])
            await self.handle_raw_status_command(data)
            return

        event_type = event.get("type", "")
        if debug_rx:
            LOGGER.info(
                "RX CoT event type=%s uid=%s",
                event_type,
                event.get("uid", ""),
            )

        if event_type != "b-t-f":
            await self.handle_raw_status_command(data)
            return

        detail = event.find("detail")
        if detail is None:
            return

        chat = detail.find("__chat")
        remarks = detail.find("remarks")
        if chat is None or remarks is None:
            if debug_rx:
                LOGGER.info("RX GeoChat missing __chat or remarks: %r", cot_xml[:400])
            return

        message = (remarks.text or "").strip()
        sender_callsign = chat.get("senderCallsign", "unknown")
        chat_room = chat.get("chatroom", chat.get("id", "unknown"))
        LOGGER.info(
            "Received GeoChat from=%s room=%s message=%s",
            sender_callsign,
            chat_room,
            message,
        )

        own_uid = self.config.get("TAK_UID", "pytak-client-001")
        own_callsign = self.config.get("TAK_CALLSIGN", "PyTAK Client")
        if remarks.get("source") == own_uid or sender_callsign == own_callsign:
            return

        command = self.config.get("TAK_CHAT_STATUS_COMMAND", "Estado").strip()
        if message.casefold() != command.casefold():
            await self.handle_raw_status_command(data)
            return

        await self.send_status_response(room=chat_room)


class ChatDatagramReceiveWorker:
    """Lee datagramas UDP CoT directamente y los procesa como GeoChat."""

    def __init__(self, reader, tx_queue, config: SectionProxy):
        self.reader = reader
        self.chat_worker = ChatReceiveWorker(asyncio.Queue(), tx_queue, config)

    async def run(self) -> None:
        LOGGER.info("Running: %s", self.__class__.__name__)
        while True:
            data, addr = await self.reader.recv()
            if self.chat_worker.config.getboolean("TAK_CHAT_DEBUG_RX", fallback=False):
                LOGGER.info("RX UDP datagram from=%s bytes=%s", addr, len(data))
            await self.chat_worker.handle_data(data)


class MavlinkPositionWorker(pytak.QueueWorker):
    """Lee posicion MAVLink desde el CubePilot y la publica como CoT."""

    def __init__(self, tx_queue, config: SectionProxy, position_state: PositionState):
        super().__init__(tx_queue, config)
        self.interval = float(config.get("TAK_INTERVAL", "1"))
        self.connection = config.get("MAVLINK_CONNECTION", "/dev/ttyACM0")
        self.baudrate = int(config.get("MAVLINK_BAUDRATE", "115200"))
        self.heartbeat_timeout = int(config.get("MAVLINK_HEARTBEAT_TIMEOUT", "30"))
        self.message_timeout = int(config.get("MAVLINK_MESSAGE_TIMEOUT", "5"))
        self.previous_position: tuple[float, float] | None = None
        self.position_state = position_state

    async def run(self) -> None:
        LOGGER.info(
            "Connecting to MAVLink connection=%s baud=%s",
            self.connection,
            self.baudrate,
        )
        mav = mavutil.mavlink_connection(self.connection, baud=self.baudrate)
        await asyncio.to_thread(mav.wait_heartbeat, timeout=self.heartbeat_timeout)
        LOGGER.info(
            "MAVLink heartbeat received system=%s component=%s",
            mav.target_system,
            mav.target_component,
        )

        while True:
            msg = await asyncio.to_thread(
                mav.recv_match,
                type="GLOBAL_POSITION_INT",
                blocking=True,
                timeout=self.message_timeout,
            )

            if msg is None:
                LOGGER.warning("No GLOBAL_POSITION_INT received from MAVLink")
                continue

            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            hae = msg.alt / 1000.0
            self.position_state.update(lat, lon, hae)
            ce = self.config.get("TAK_CE", "10.0")
            le = self.config.get("TAK_LE", "10.0")
            course, speed = course_speed_from_global_position(msg)
            if course is None and self.previous_position is not None:
                previous_lat, previous_lon = self.previous_position
                course = bearing_between_points(previous_lat, previous_lon, lat, lon)
            self.previous_position = (lat, lon)

            event = build_position_event_from_values(
                config=self.config,
                lat=lat,
                lon=lon,
                hae=hae,
                ce=ce,  
                le=le,
                course=round(course, 1) if course is not None else None,
                speed=round(speed, 2) if speed is not None else None,
            )
            await self.put_queue(event)
            LOGGER.info(
                "Sent CoT from MAVLink lat=%s lon=%s hae=%s course=%s speed=%s",
                lat,
                lon,
                hae,
                course,
                speed,
            )
            await asyncio.sleep(self.interval)


async def main() -> None:
    config = load_config()

    logging.basicConfig(
        level=logging.DEBUG if config.getboolean("DEBUG", fallback=False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    original_cot_url = config.get("COT_URL", pytak.DEFAULT_COT_URL)
    cot_url_scheme = urlparse(original_cot_url).scheme
    use_udp_bind_all = (
        config.getboolean("TAK_CHAT_ENABLE", fallback=False)
        and config.getboolean("TAK_CHAT_UDP_BIND_ALL", fallback=True)
        and "udp" in cot_url_scheme
        and "+wo" not in urlparse(original_cot_url).scheme
    )
    LOGGER.info(
        "Chat UDP config: COT_URL=%s scheme=%s TAK_CHAT_ENABLE=%s "
        "TAK_CHAT_UDP_BIND_ALL=%s use_udp_bind_all=%s",
        original_cot_url,
        cot_url_scheme,
        config.getboolean("TAK_CHAT_ENABLE", fallback=False),
        config.getboolean("TAK_CHAT_UDP_BIND_ALL", fallback=True),
        use_udp_bind_all,
    )

    if use_udp_bind_all:
        config["COT_URL"] = udp_write_only_url(original_cot_url)

    reader, writer = await pytak.protocol_factory(config)

    if use_udp_bind_all:
        config["COT_URL"] = original_cot_url
        reader = await create_udp_bind_all_reader(original_cot_url)

    max_out_queue = int(config.get("MAX_OUT_QUEUE") or pytak.DEFAULT_MAX_OUT_QUEUE)
    max_in_queue = int(config.get("MAX_IN_QUEUE") or pytak.DEFAULT_MAX_IN_QUEUE)
    tx_queue = asyncio.Queue(max_out_queue)
    rx_queue = asyncio.Queue(max_in_queue)

    tx_worker = pytak.TXWorker(tx_queue, config, writer)
    position_state = PositionState(config)
    source = config.get("TAK_SOURCE", "static").strip().lower()
    worker_cls = MavlinkPositionWorker if source == "mavlink" else PositionWorker
    tasks = [
        asyncio.create_task(tx_worker.run(), name="pytak-tx"),
        asyncio.create_task(
            worker_cls(tx_queue, config, position_state).run(),
            name="position-source",
        ),
    ]

    if config.getboolean("TAK_CHAT_ENABLE", fallback=False):
        tasks.append(
            asyncio.create_task(
                ChatAnnounceWorker(tx_queue, config, position_state).run(),
                name="chat-announce",
            )
        )
        if reader is not None:
            if use_udp_bind_all:
                LOGGER.info("Using direct UDP datagram chat receiver")
                tasks.append(
                    asyncio.create_task(
                        ChatDatagramReceiveWorker(reader, tx_queue, config).run(),
                        name="chat-udp-receive",
                    )
                )
            else:
                rx_worker = pytak.RXWorker(rx_queue, config, reader)
                tasks.extend(
                    [
                        asyncio.create_task(rx_worker.run(), name="pytak-rx"),
                        asyncio.create_task(
                            ChatReceiveWorker(rx_queue, tx_queue, config).run(),
                            name="chat-receive",
                        ),
                    ]
                )
        else:
            LOGGER.warning("TAK_CHAT_ENABLE=1 but COT_URL is write-only; chat RX disabled")

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            raise exc
        raise RuntimeError(f"Worker exited unexpectedly: {task.get_name()}")


def run() -> None:
    asyncio.run(main())
