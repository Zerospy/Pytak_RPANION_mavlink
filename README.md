# Cliente TAK basico con PyTAK

Estructura minima para levantar un cliente TAK que emite eventos CoT periodicos usando PyTAK.
Puede emitir una posicion fija para pruebas o leer `GLOBAL_POSITION_INT` directo desde un CubePilot por MAVLink.

## Requisitos

- Python 3.10+
- Un servidor TAK, un cliente ATAK/WinTAK, o salida local por consola
- Para CubePilot: acceso al puerto serie MAVLink, por ejemplo `/dev/ttyACM0`

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## Configuracion

Edita `.env`:

```env
COT_URL=log://stdout
TAK_UID=pytak-client-001
TAK_CALLSIGN=PyTAK Client
TAK_LAT=-33.4489
TAK_LON=-70.6693
TAK_INTERVAL=10
```

Para leer directo desde CubePilot:

```env
COT_URL=udp://10.147.17.25:8087
TAK_SOURCE=mavlink
TAK_UID=USV-CUBEPILOT-001
TAK_CALLSIGN=USV-01
TAK_INTERVAL=1
TAK_CE=10
TAK_LE=10
MAVLINK_CONNECTION=/dev/ttyACM0
MAVLINK_BAUDRATE=115200
```

En Linux/WSL puedes revisar el puerto con:

```bash
ls /dev/ttyACM*
```

Valores comunes para `COT_URL`:

- `log://stdout`: imprime CoT en consola, util para pruebas.
- `tcp://host:port`: TCP sin TLS.
- `tls://host:port`: TAK Server con TLS.
- `udp://239.2.3.1:6969`: multicast Mesh SA.

Para TLS, agrega en `.env` las rutas a certificados PEM:

```env
PYTAK_TLS_CLIENT_CERT=certs/client.pem
PYTAK_TLS_CLIENT_KEY=certs/client.key
PYTAK_TLS_DONT_VERIFY=0
```

## Ejecucion

```powershell
python -m tak_client
```

Primero prueba con `COT_URL=log://stdout`. Cuando veas XML CoT en consola, cambia `COT_URL` al destino TAK real.
