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
    course: Union[float, str, None] = None,
    speed: Union[float, str, None] = None,
) -> bytes:
    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", config.get("TAK_UID", "pytak-client-001"))
    event.set("type", "a-f-S-U")
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

    group = ET.SubElement(detail, "__group")
    group.set("name", config.get("TAK_GROUP_NAME", "Cyan"))
    group.set("role", config.get("TAK_GROUP_ROLE", "Team Member"))

    takv = ET.SubElement(detail, "takv")
    takv.set("device", config.get("TAK_PLATFORM", "PyTAK RPANION"))
    takv.set("platform", config.get("TAK_PLATFORM", "PyTAK RPANION"))
    takv.set("version", config.get("TAK_VERSION", "1.0"))

    if course is not None:
        track = ET.SubElement(detail, "track")
        track.set("course", str(course))
        if speed is not None:
            track.set("speed", str(speed))

    return ET.tostring(event)
