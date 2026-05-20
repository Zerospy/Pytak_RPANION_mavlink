import xml.etree.ElementTree as ET
from configparser import SectionProxy
from typing import Union

import pytak


def build_position_event(config: SectionProxy) -> bytes:
    return build_position_event_from_values(
        config=config,
        lat=config.get("TAK_LAT", "0"),
        lon=config.get("TAK_LON", "0"),
        hae=config.get("TAK_HAE", "0"),
        ce=config.get("TAK_CE", "9999999"),
        le=config.get("TAK_LE", "9999999"),
    )


def build_position_event_from_values(
    config: SectionProxy,
    lat: Union[float, str],
    lon: Union[float, str],
    hae: Union[float, str],
    ce: Union[float, str] = "10.0",
    le: Union[float, str] = "10.0",
) -> bytes:
    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", config.get("TAK_UID", "pytak-client-001"))
    event.set("type", "a-f-G-U-C")
    event.set("how", "m-g")
    event.set("time", pytak.cot_time())
    event.set("start", pytak.cot_time())
    event.set("stale", pytak.cot_time(120))

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lon))
    point.set("hae", str(hae))
    point.set("ce", str(ce))
    point.set("le", str(le))

    detail = ET.SubElement(event, "detail")
    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", config.get("TAK_CALLSIGN", "Cliente PyTAK"))

    return ET.tostring(event)
