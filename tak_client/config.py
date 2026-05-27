import os
from configparser import ConfigParser, SectionProxy
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config() -> SectionProxy:
    load_env_file()

    parser = ConfigParser()
    parser["tak_client"] = {
        "COT_URL": os.getenv("COT_URL", "log://stdout"),
        "TAK_PROTO": os.getenv("TAK_PROTO", "0"),
        "TAK_UID": os.getenv("TAK_UID", "pytak-client-001"),
        "TAK_CALLSIGN": os.getenv("TAK_CALLSIGN", "PyTAK Client"),
        "TAK_LAT": os.getenv("TAK_LAT", "-33.020771"),
        "TAK_LON": os.getenv("TAK_LON", "-71.637703"),
        "TAK_HAE": os.getenv("TAK_HAE", "0"),
        "TAK_CE": os.getenv("TAK_CE", "9999999"),
        "TAK_LE": os.getenv("TAK_LE", "9999999"),
        "TAK_INTERVAL": os.getenv("TAK_INTERVAL", "10"),
        "TAK_GROUP_NAME": os.getenv("TAK_GROUP_NAME", "Cyan"),
        "TAK_GROUP_ROLE": os.getenv("TAK_GROUP_ROLE", "Team Member"),
        "TAK_PLATFORM": os.getenv("TAK_PLATFORM", "PyTAK RPANION"),
        "TAK_VERSION": os.getenv("TAK_VERSION", "1.0"),
        "TAK_SOURCE": os.getenv("TAK_SOURCE", "static"),
        "MAVLINK_CONNECTION": os.getenv("MAVLINK_CONNECTION", "/dev/ttyACM0"),
        "MAVLINK_BAUDRATE": os.getenv("MAVLINK_BAUDRATE", "115200"),
        "MAVLINK_HEARTBEAT_TIMEOUT": os.getenv("MAVLINK_HEARTBEAT_TIMEOUT", "30"),
        "MAVLINK_MESSAGE_TIMEOUT": os.getenv("MAVLINK_MESSAGE_TIMEOUT", "5"),
    }

    for key in (
        "PYTAK_TLS_CLIENT_CERT",
        "PYTAK_TLS_CLIENT_KEY",
        "PYTAK_TLS_CLIENT_CAFILE",
        "PYTAK_TLS_DONT_VERIFY",
        "DEBUG",
    ):
        value = os.getenv(key)
        if value is not None:
            parser["tak_client"][key] = value

    return parser["tak_client"]
