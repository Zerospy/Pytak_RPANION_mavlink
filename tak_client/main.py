import asyncio
import logging
from configparser import SectionProxy

import pytak
from pymavlink import mavutil

from .config import load_config
from .cot import build_position_event, build_position_event_from_values


LOGGER = logging.getLogger(__name__)


class PositionWorker(pytak.QueueWorker):
    """Genera una posicion simple recurrente."""

    def __init__(self, tx_queue, config: SectionProxy):
        super().__init__(tx_queue, config)
        self.interval = int(config.get("TAK_INTERVAL", "10"))

    async def run(self) -> None:
        while True:
            event = build_position_event(self.config)
            await self.put_queue(event)
            LOGGER.info("Sent CoT position event uid=%s", self.config.get("TAK_UID"))
            await asyncio.sleep(self.interval)


class MavlinkPositionWorker(pytak.QueueWorker):
    """Lee posicion MAVLink desde el CubePilot y la publica como CoT."""

    def __init__(self, tx_queue, config: SectionProxy):
        super().__init__(tx_queue, config)
        self.interval = float(config.get("TAK_INTERVAL", "1"))
        self.connection = config.get("MAVLINK_CONNECTION", "/dev/ttyACM0")
        self.baudrate = int(config.get("MAVLINK_BAUDRATE", "115200"))
        self.heartbeat_timeout = int(config.get("MAVLINK_HEARTBEAT_TIMEOUT", "30"))
        self.message_timeout = int(config.get("MAVLINK_MESSAGE_TIMEOUT", "5"))

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
            ce = self.config.get("TAK_CE", "10.0")
            le = self.config.get("TAK_LE", "10.0")

            event = build_position_event_from_values(
                config=self.config,
                lat=lat,
                lon=lon,
                hae=hae,
                ce=ce,  
                le=le,
            )
            await self.put_queue(event)
            LOGGER.info("Sent CoT from MAVLink lat=%s lon=%s hae=%s", lat, lon, hae)
            await asyncio.sleep(self.interval)


async def main() -> None:
    config = load_config()

    logging.basicConfig(
        level=logging.DEBUG if config.getboolean("DEBUG", fallback=False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    clitool = pytak.CLITool(config)
    await clitool.setup()
    source = config.get("TAK_SOURCE", "static").strip().lower()
    worker_cls = MavlinkPositionWorker if source == "mavlink" else PositionWorker
    clitool.add_tasks({worker_cls(clitool.tx_queue, config)})
    await clitool.run()


def run() -> None:
    asyncio.run(main())
