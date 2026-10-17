#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Klingel-Dashboard Brume 2  –  v4.0.1
====================================

Laeuft auf einem GL.iNet Brume 2 (GL-MT2500, OpenWrt) im Autostart und stellt bereit:

  * Dashboard 1 (Standard-Port 8081) und Dashboard 2 (Standard-Port 8082)
      - Kamerabild (RTSP -> ffmpeg -> MJPEG, auch fuer iPad mini 1 / iOS 9)
      - Türöffner-Taste: beide Dashboards senden denselben MQTT-Befehl an denselben Broker
      - bis zu 3 Klingel-Symbole je Dashboard mit eigenen MQTT-Topics, Klingelton im Browser
  * Einrichtungsseite (Standard-Port 8083): Broker, Topics, Kameras, Ports, Kameratest

Nur Python-Standardbibliothek (Python >= 3.7), dazu ffmpeg mit H.264-Decoder.
Konfiguration: config.ini im Programmordner (menschenlesbar).
"""

import base64
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import select
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

APP_NAME = "Klingel-Dashboard Brume 2"
APP_VERSION = "4.0.1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("KLINGEL_CONFIG") or os.path.join(BASE_DIR, "config.ini")
WEB_DIR = os.path.join(BASE_DIR, "web")

NUM_SITES = 2
NUM_BELLS = 3
BELL_ACTIVE_S = 3.0          # Klingel-Symbol bleibt 3 s aktiv
CAM_LINGER_S = 30.0          # Kamera läuft nach dem letzten Zuschauer noch 30 s weiter
CAM_FIRST_FRAME_S = 20.0     # so lange darf das erste Bild dauern
CAM_STALL_S = 12.0           # kein neues Bild -> ffmpeg neu starten
START_TIME = time.time()


LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "klingel.log")
LOG_MAX = 256 * 1024          # danach -> klingel.log.1 (schont den Flash)
_LOG_LOCK = threading.Lock()


def log(tag, msg):
    line = "[%s] [%s] %s\n" % (time.strftime("%H:%M:%S"), tag, msg)
    sys.stdout.write(line)
    sys.stdout.flush()
    with _LOG_LOCK:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX:
                os.replace(LOG_FILE, LOG_FILE + ".1")
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d ") + line)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#   Konfiguration (Schema -> config.ini, Einrichtungsseite, Validierung)
# ═══════════════════════════════════════════════════════════════════════════

def _f(sec, key, typ, default, label, hint="", **kw):
    d = {"sec": sec, "key": key, "type": typ, "default": default, "label": label, "hint": hint}
    d.update(kw)
    return d


def build_schema():
    s = [
        _f("allgemein", "einrichtung_port", "port", 8083, "Port der Einrichtungsseite"),
        _f("allgemein", "admin_passwort", "pass", "", "Passwort der Einrichtungsseite",
           "leer = kein Schutz, Benutzername beliebig"),
        _f("allgemein", "firewall_freigeben", "bool", True, "Ports in der Brume-Firewall freigeben",
           "nötig, wenn die Dashboards über den WAN-Port erreicht werden"),
        _f("allgemein", "ffmpeg_pfad", "str", "", "Pfad zu ffmpeg",
           "leer = automatisch (bin/ffmpeg im Programmordner, sonst System)"),

        _f("mqtt", "broker", "str", "192.168.1.100", "Broker (IP oder Hostname)"),
        _f("mqtt", "port", "port", 1883, "Broker-Port"),
        _f("mqtt", "benutzer", "str", "", "Benutzer", "leer = ohne Anmeldung"),
        _f("mqtt", "passwort", "pass", "", "Passwort"),
        _f("mqtt", "client_id", "str", "klingel-brume2", "Client-ID"),

        _f("oeffner", "topic_druecken", "str", "doorbell/opener", "Topic beim Drücken"),
        _f("oeffner", "payload_druecken", "str", "OPEN", "Payload beim Drücken"),
        _f("oeffner", "topic_loslassen", "str", "doorbell/opener", "Topic beim Loslassen",
           "leer = beim Loslassen nichts senden"),
        _f("oeffner", "payload_loslassen", "str", "CLOSE", "Payload beim Loslassen"),
        _f("oeffner", "wiederholung_ms", "int", 500, "Wiederholung solange gedrückt (ms)",
           "der Drücken-Befehl wird in diesem Abstand wiederholt", min=100, max=5000),
    ]
    for n in range(1, NUM_SITES + 1):
        sec = "dashboard%d" % n
        s += [
            _f(sec, "port", "port", 8080 + n, "Port"),
            _f(sec, "titel", "str", "Eingang %d" % n, "Titel"),
            _f(sec, "kamera_typ", "choice", "rtsp", "Kameraquelle",
               "rtsp = Videostream über ffmpeg (RTSP oder HTTP), jpeg = Standbild-URL der Kamera",
               options=["rtsp", "jpeg", "aus"]),
            _f(sec, "kamera_url", "str",
               "rtsp://192.168.1.%d:554/stream2" % (199 + n), "Kamera-URL",
               "dieselbe URL wie in VLC; Zugangsdaten besser in die Felder darunter"),
            _f(sec, "kamera_benutzer", "str", "", "Kamera-Benutzer"),
            _f(sec, "kamera_passwort", "pass", "", "Kamera-Passwort"),
            _f(sec, "rtsp_transport", "choice", "tcp", "RTSP-Transport",
               "tcp ist fast immer richtig", options=["tcp", "udp"]),
            _f(sec, "bilder_pro_sekunde", "int", 8, "Bilder pro Sekunde", min=1, max=25),
            _f(sec, "max_breite", "int", 960, "Maximale Bildbreite (Pixel)",
               "kleiner = weniger Last für Brume und iPad", min=160, max=1920),
            _f(sec, "jpeg_qualitaet", "int", 75, "JPEG-Qualität (%)", min=30, max=95),
            _f(sec, "sparmodus", "bool", False, "Sparmodus (nur Schlüsselbilder)",
               "sehr wenig CPU, dafür meist nur 1 Bild pro Sekunde oder weniger"),
            _f(sec, "immer_aktiv", "bool", False, "Kamera dauerhaft abrufen",
               "sonst nur, solange ein Dashboard sie anzeigt (+30 s)"),
            _f(sec, "bildmodus", "choice", "auto", "Bildmodus im Browser",
               "auto = Video (MJPEG), bei Problemen automatisch Einzelbilder",
               options=["auto", "mjpeg", "einzelbild"]),
        ]
        for b in range(1, NUM_BELLS + 1):
            s += [
                _f(sec, "klingel%d_name" % b, "str", "B%d" % b, "Klingel %d Name" % b),
                _f(sec, "klingel%d_topic" % b, "str", ("doorbell/bell%d" % n) if b == 1 else "",
                   "Klingel %d Topic" % b, "leer = Symbol ausgeblendet; + und # erlaubt"),
                _f(sec, "klingel%d_payload" % b, "str", "RING", "Klingel %d Payload" % b,
                   "leer = jede Nachricht auf dem Topic klingelt"),
            ]
    return s


SCHEMA = build_schema()
SECTION_TITLES = {
    "allgemein": "Allgemein",
    "mqtt": "MQTT-Broker",
    "oeffner": "Türöffner (beide Dashboards)",
}
for _n in range(1, NUM_SITES + 1):
    SECTION_TITLES["dashboard%d" % _n] = "Dashboard %d" % _n


def fid(f):
    return "%s.%s" % (f["sec"], f["key"])


def parse_bool(v):
    return str(v).strip().lower() in ("1", "ja", "true", "yes", "on", "an", "wahr")


def coerce(f, raw):
    """Rohwert (Text) -> typisierter Wert; wirft ValueError mit deutscher Meldung."""
    t = f["type"]
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        return parse_bool(raw)
    if t in ("int", "port"):
        try:
            v = int(str(raw).strip())
        except ValueError:
            raise ValueError("%s: '%s' ist keine Zahl" % (f["label"], raw))
        lo, hi = (1, 65535) if t == "port" else (f.get("min", -10 ** 9), f.get("max", 10 ** 9))
        if v < lo or v > hi:
            raise ValueError("%s: %d liegt nicht zwischen %d und %d" % (f["label"], v, lo, hi))
        return v
    if t == "choice":
        v = str(raw).strip().lower()
        if v not in f["options"]:
            raise ValueError("%s: erlaubt sind %s" % (f["label"], ", ".join(f["options"])))
        return v
    v = str(raw).replace("\r", "").replace("\n", " ").strip()
    if len(v) > 300:
        raise ValueError("%s: zu lang" % f["label"])
    return v


def read_ini(path):
    data = {}
    sec = None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line or line[0] in "#;":
                    continue
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1].strip().lower()
                    continue
                if "=" in line and sec:
                    k, v = line.split("=", 1)
                    data["%s.%s" % (sec, k.strip().lower())] = v.strip()
    except FileNotFoundError:
        return None
    return data


def load_config():
    raw = read_ini(CONFIG_PATH)
    cfg = {}
    problems = []
    for f in SCHEMA:
        k = fid(f)
        if raw is not None and k in raw:
            try:
                cfg[k] = coerce(f, raw[k])
            except ValueError as e:
                problems.append(str(e))
                cfg[k] = f["default"]
        else:
            cfg[k] = f["default"]
    if raw is None:
        save_config(cfg)
        log("CFG", "config.ini neu angelegt: %s" % CONFIG_PATH)
    for p in problems:
        log("CFG", "WARNUNG %s -> Standardwert" % p)
    return cfg


def fmt_value(f, v):
    if f["type"] == "bool":
        return "ja" if v else "nein"
    return str(v)


def save_config(cfg):
    lines = [
        "# ================================================================",
        "#  %s  -  Konfiguration" % APP_NAME,
        "#  Wird auch von der Einrichtungsseite geschrieben.",
        "#  Nach Änderung von Hand: /etc/init.d/klingel-dashboard restart",
        "# ================================================================",
        "",
    ]
    cur = None
    for f in SCHEMA:
        if f["sec"] != cur:
            cur = f["sec"]
            if lines[-1] != "":
                lines.append("")
            lines.append("[%s]" % cur)
        c = f["label"]
        if f["type"] == "choice":
            c += " (" + " | ".join(f["options"]) + ")"
        elif f["type"] == "bool":
            c += " (ja | nein)"
        if f.get("hint"):
            c += " - " + f["hint"]
        lines.append("# " + c)
        lines.append("%s = %s" % (f["key"], fmt_value(f, cfg[fid(f)])))
    text = "\n".join(lines) + "\n"
    tmp = CONFIG_PATH + ".neu"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, CONFIG_PATH)


CFG = load_config()


def site_cfg(n):
    """Teil-Konfiguration eines Dashboards als dict ohne Sektionspraefix."""
    p = "dashboard%d." % n
    return {k[len(p):]: v for k, v in CFG.items() if k.startswith(p)}


def site_bells(n):
    sc = site_cfg(n)
    out = []
    for b in range(1, NUM_BELLS + 1):
        t = sc["klingel%d_topic" % b]
        if t:
            out.append({"id": b, "name": sc["klingel%d_name" % b] or ("B%d" % b),
                        "topic": t, "payload": sc["klingel%d_payload" % b]})
    return out


# ═══════════════════════════════════════════════════════════════════════════
#   MQTT (minimaler 3.1.1-Client, QoS 0/1 empfangen, QoS 0 senden)
# ═══════════════════════════════════════════════════════════════════════════

def topic_matches(flt, topic):
    if flt == topic:
        return True
    fp, tp = flt.split("/"), topic.split("/")
    for i, part in enumerate(fp):
        if part == "#":
            return True
        if i >= len(tp):
            return False
        if part != "+" and part != tp[i]:
            return False
    return len(fp) == len(tp)


def _mqtt_str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _mqtt_len(n):
    out = bytearray()
    while True:
        d = n % 128
        n //= 128
        if n:
            d |= 0x80
        out.append(d)
        if not n:
            return bytes(out)


class MQTTClient(threading.Thread):
    KEEPALIVE = 30

    def __init__(self, on_message):
        threading.Thread.__init__(self, daemon=True, name="mqtt")
        self.on_message = on_message
        self.sock = None
        self.connected = False
        self.state = "startet"
        self.send_lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.last_tx = 0.0
        self.last_rx = 0.0
        self.pkt_id = 1

    # -- Hilfen --------------------------------------------------------------
    def _send(self, data):
        with self.send_lock:
            if not self.sock:
                raise OSError("keine Verbindung")
            self.sock.sendall(data)
            self.last_tx = time.time()

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("Verbindung vom Broker geschlossen")
            buf += chunk
        return bytes(buf)

    def _read_packet(self, first_byte):
        mult, rl = 1, 0
        for _ in range(4):
            d = self._recv_exact(1)[0]
            rl += (d & 0x7F) * mult
            mult *= 128
            if not d & 0x80:
                break
        else:
            raise OSError("MQTT-Protokollfehler")
        body = self._recv_exact(rl) if rl else b""
        return first_byte, body

    def topics(self):
        seen = []
        for n in range(1, NUM_SITES + 1):
            for b in site_bells(n):
                if b["topic"] not in seen:
                    seen.append(b["topic"])
        return seen

    # -- Ablauf --------------------------------------------------------------
    def run(self):
        while not self.stop_evt.is_set():
            host, port = CFG["mqtt.broker"], CFG["mqtt.port"]
            if not host:
                self.state = "kein Broker eingetragen"
                time.sleep(5)
                continue
            try:
                self.state = "verbinde mit %s:%d" % (host, port)
                self._session(host, port)
            except Exception as e:  # noqa
                msg = str(e) or e.__class__.__name__
                if isinstance(e, socket.timeout):
                    msg = "Zeitüberschreitung"
                elif isinstance(e, ConnectionRefusedError):
                    msg = "Verbindung abgelehnt (Port/Broker prüfen)"
                elif isinstance(e, socket.gaierror):
                    msg = "Hostname nicht auflösbar"
                if self.connected or not self.state.startswith("Fehler"):
                    log("MQTT", "getrennt: %s" % msg)
                self.state = "Fehler: %s" % msg
            finally:
                self.connected = False
                with self.send_lock:
                    if self.sock:
                        try:
                            self.sock.close()
                        except OSError:
                            pass
                    self.sock = None
            self.stop_evt.wait(3)

    def _session(self, host, port):
        s = socket.create_connection((host, port), timeout=6)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self.send_lock:
            self.sock = s
        # CONNECT
        user, pw = CFG["mqtt.benutzer"], CFG["mqtt.passwort"]
        flags = 0x02
        payload = _mqtt_str(CFG["mqtt.client_id"] or ("klingel-%d" % os.getpid()))
        if user:
            flags |= 0x80
            payload += _mqtt_str(user)
            if pw:
                flags |= 0x40
                payload += _mqtt_str(pw)
        vh = _mqtt_str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.KEEPALIVE)
        body = vh + payload
        self._send(b"\x10" + _mqtt_len(len(body)) + body)
        hdr, body = self._read_packet(self._recv_exact(1)[0])
        if hdr >> 4 != 2 or len(body) < 2:
            raise OSError("unerwartete Antwort statt CONNACK")
        if body[1] != 0:
            reasons = {1: "Protokollversion abgelehnt", 2: "Client-ID abgelehnt", 3: "Broker nicht verfügbar",
                       4: "Benutzer/Passwort falsch", 5: "nicht berechtigt"}
            raise OSError("Broker lehnt ab: %s" % reasons.get(body[1], "Code %d" % body[1]))
        # SUBSCRIBE
        tops = self.topics()
        if tops:
            pid = self._next_id()
            sb = struct.pack("!H", pid) + b"".join(_mqtt_str(t) + b"\x00" for t in tops)
            self._send(b"\x82" + _mqtt_len(len(sb)) + sb)
        self.connected = True
        self.state = "verbunden mit %s:%d" % (host, port)
        self.last_rx = time.time()
        log("MQTT", "%s, abonniert: %s" % (self.state, ", ".join(tops) or "-"))
        s.settimeout(1.0)
        while not self.stop_evt.is_set():
            try:
                first = s.recv(1)
            except socket.timeout:
                first = None
            now = time.time()
            if first is not None:
                if not first:
                    raise OSError("Verbindung vom Broker geschlossen")
                s.settimeout(10)
                hdr, body = self._read_packet(first[0])
                s.settimeout(1.0)
                self.last_rx = now
                self._on_packet(hdr, body)
            if now - self.last_tx > self.KEEPALIVE / 2:
                self._send(b"\xc0\x00")
            if now - self.last_rx > self.KEEPALIVE * 1.5:
                raise OSError("Broker antwortet nicht mehr")

    def _next_id(self):
        self.pkt_id = self.pkt_id % 65535 + 1
        return self.pkt_id

    def _on_packet(self, hdr, body):
        typ = hdr >> 4
        if typ == 3:
            qos = (hdr >> 1) & 3
            tl = struct.unpack("!H", body[:2])[0]
            topic = body[2:2 + tl].decode("utf-8", "replace")
            off = 2 + tl
            if qos:
                pid = body[off:off + 2]
                off += 2
                if qos == 1:
                    self._send(b"\x40\x02" + pid)
                elif qos == 2:
                    self._send(b"\x50\x02" + pid)
            try:
                self.on_message(topic, body[off:])
            except Exception as e:  # noqa
                log("MQTT", "Fehler bei Nachricht: %s" % e)
        elif typ == 6:      # PUBREL (QoS 2) -> PUBCOMP
            self._send(b"\x70\x02" + body[:2])

    def publish(self, topic, payload):
        if not topic:
            return False
        if not self.connected:
            log("MQTT", "nicht verbunden - %s nicht gesendet" % topic)
            return False
        body = _mqtt_str(topic) + payload.encode("utf-8")
        try:
            self._send(b"\x30" + _mqtt_len(len(body)) + body)
            log("MQTT", "-> %s: %s" % (topic, payload))
            return True
        except OSError as e:
            log("MQTT", "Senden fehlgeschlagen: %s" % e)
            return False

    def stop(self):
        self.stop_evt.set()


# ═══════════════════════════════════════════════════════════════════════════
#   Klingel-Zustand
# ═══════════════════════════════════════════════════════════════════════════

BELL_LOCK = threading.Lock()
BELL_COUNT = {}     # (site, bell) -> Anzahl
BELL_UNTIL = {}     # (site, bell) -> Zeitpunkt bis aktiv


def ring(site, bell, reason):
    with BELL_LOCK:
        BELL_COUNT[(site, bell)] = BELL_COUNT.get((site, bell), 0) + 1
        BELL_UNTIL[(site, bell)] = time.time() + BELL_ACTIVE_S
    log("KLINGEL", "Dashboard %d / Klingel %d (%s)" % (site, bell, reason))


def on_mqtt_message(topic, payload):
    text = payload.decode("utf-8", "replace").strip()
    log("MQTT", "<- %s: %s" % (topic, text[:80]))
    for n in range(1, NUM_SITES + 1):
        for b in site_bells(n):
            if not topic_matches(b["topic"], topic):
                continue
            if b["payload"] and b["payload"].strip() != text:
                continue
            ring(n, b["id"], "MQTT %s" % topic)


# ═══════════════════════════════════════════════════════════════════════════
#   ffmpeg
# ═══════════════════════════════════════════════════════════════════════════

FFMPEG = {"path": "", "version": "", "h264": False, "hevc": False, "checked": False}


def find_ffmpeg():
    cands = []
    if CFG["allgemein.ffmpeg_pfad"]:
        cands.append(CFG["allgemein.ffmpeg_pfad"])
    cands += [os.path.join(BASE_DIR, "bin", "ffmpeg"), shutil.which("ffmpeg") or "", "/usr/bin/ffmpeg"]
    best = None
    for c in cands:
        if not c or not os.path.isfile(c) or not os.access(c, os.X_OK):
            continue
        info = {"path": c, "version": "", "h264": False, "hevc": False, "checked": True}
        try:
            v = subprocess.run([c, "-hide_banner", "-version"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=20).stdout.decode("utf-8", "replace")
            m = re.search(r"ffmpeg version (\S+)", v)
            info["version"] = m.group(1) if m else "?"
            mm = re.match(r"n?(\d+)\.", info["version"])
            info["major"] = int(mm.group(1)) if mm else 99
            d = subprocess.run([c, "-hide_banner", "-decoders"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=20).stdout.decode("utf-8", "replace")
            info["h264"] = bool(re.search(r"^\s*V\S*\s+h264\s", d, re.M))
            info["hevc"] = bool(re.search(r"^\s*V\S*\s+hevc\s", d, re.M))
        except Exception as e:  # noqa
            log("FFMPEG", "%s nicht nutzbar: %s" % (c, e))
            continue
        if info["h264"]:
            best = info
            break
        if best is None:
            best = info
    FFMPEG.clear()
    FFMPEG.update(best or {"path": "", "version": "", "h264": False, "hevc": False, "checked": True})
    if FFMPEG["path"]:
        log("FFMPEG", "%s (Version %s, H.264: %s, H.265: %s)" % (
            FFMPEG["path"], FFMPEG["version"], "ja" if FFMPEG["h264"] else "NEIN",
            "ja" if FFMPEG["hevc"] else "nein"))
        if not FFMPEG["h264"]:
            log("FFMPEG", "WARNUNG: diesem ffmpeg fehlt der H.264-Decoder (OpenWrt-Paket). "
                          "install.sh installiert eine passende Version nach bin/ffmpeg.")
    else:
        log("FFMPEG", "WARNUNG: kein ffmpeg gefunden - RTSP-Kameras funktionieren nicht")


def explain_ffmpeg_error(text):
    t = text.lower()
    rules = [
        ("401", "Anmeldung abgelehnt - Kamera-Benutzer/Passwort prüfen"),
        ("unauthorized", "Anmeldung abgelehnt - Kamera-Benutzer/Passwort prüfen"),
        ("403", "Zugriff verweigert (403) - Benutzerrechte der Kamera prüfen"),
        ("404", "Pfad nicht gefunden (404) - Stream-Pfad der URL prüfen"),
        ("454", "Stream nicht gefunden (454) - Stream-Pfad der URL prüfen"),
        ("connection refused", "Verbindung abgelehnt - IP/Port prüfen, RTSP in der Kamera aktiv?"),
        ("no route to host", "Kamera nicht erreichbar (keine Route) - IP und Netz prüfen"),
        ("network is unreachable", "Netz nicht erreichbar - Brume-Netzwerk prüfen"),
        ("timed out", "Zeitüberschreitung - Kamera antwortet nicht"),
        ("timeout", "Zeitüberschreitung - Kamera antwortet nicht"),
        ("name or service not known", "Hostname nicht auflösbar"),
        ("invalid data found", "Kamera liefert unlesbare Daten - URL/Stream prüfen"),
        ("decoder (codec h264) not found", "ffmpeg ohne H.264-Decoder - install.sh erneut ausführen"),
        ("decoder (codec hevc) not found", "Kamera sendet H.265 - ffmpeg ohne H.265, Kamera auf H.264 stellen"),
        ("could not find codec parameters", "Videoformat nicht erkannt - anderen Stream (z. B. Substream) probieren"),
        ("nonmatching transport", "Transport passt nicht - RTSP-Transport auf udp/tcp umstellen"),
        ("unsupported transport", "Transport passt nicht - RTSP-Transport auf udp/tcp umstellen"),
        ("461", "Transport passt nicht - RTSP-Transport auf udp/tcp umstellen"),
        ("protocol not found", "URL-Schema nicht unterstützt (rtsp:// oder http:// verwenden)"),
    ]
    for key, msg in rules:
        if key in t:
            return msg
    return ""


def jpeg_size(data):
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack("!HH", data[i + 5:i + 9])
            return w, h
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        seg = struct.unpack("!H", data[i + 2:i + 4])[0]
        i += 2 + seg
    return 0, 0


def with_credentials(url, user, pw):
    if not user:
        return url
    p = urllib.parse.urlsplit(url)
    if "@" in p.netloc:
        return url
    cred = urllib.parse.quote(user, safe="")
    if pw:
        cred += ":" + urllib.parse.quote(pw, safe="")
    return urllib.parse.urlunsplit((p.scheme, cred + "@" + p.netloc, p.path, p.query, p.fragment))


def mask_url(url):
    return re.sub(r"(://[^:/@]+):[^@/]*@", r"\1:***@", url)


def ffmpeg_args(cam, url, single=False):
    q = int(round(2 + (95 - cam["jpeg_qualitaet"]) * 20.0 / 65.0))
    args = [FFMPEG["path"], "-hide_banner", "-nostdin", "-loglevel", "error"]
    if url.lower().startswith("rtsp"):
        args += ["-rtsp_transport", cam["rtsp_transport"]]
    if cam["sparmodus"] and not single:
        args += ["-skip_frame", "nokey"]
    args += ["-fflags", "nobuffer", "-flags", "low_delay",
             "-analyzeduration", "3000000", "-probesize", "3000000",
             "-i", url, "-an", "-sn", "-dn"]
    vf = []
    if not single:
        vf.append("select='isnan(prev_selected_t)+gte(t-prev_selected_t,%.3f)'"
                  % (1.0 / max(1, cam["bilder_pro_sekunde"]) * 0.95))
    vf.append("scale='min(%d,iw)':-2" % cam["max_breite"])
    vf.append("format=yuvj420p")
    args += ["-vf", ",".join(vf)]
    if not single:
        # keine Bildverdopplung: Bilder so weitergeben, wie der Filter sie auswaehlt
        args += (["-fps_mode", "passthrough"] if FFMPEG.get("major", 99) >= 5 else ["-vsync", "0"])
    args += ["-c:v", "mjpeg", "-q:v", str(q)]
    if single:
        args += ["-frames:v", "1", "-f", "image2", "pipe:1"]
    else:
        args += ["-flush_packets", "1", "-f", "mjpeg", "pipe:1"]
    return args


def grab_single_frame(cam, timeout=20):
    """Einmaliger Kameratest (Einrichtungsseite). -> (jpeg|None, meldung, log)"""
    typ = cam["kamera_typ"]
    url = cam["kamera_url"].strip()
    if typ == "aus" or not url:
        return None, "Kamera ist ausgeschaltet oder keine URL eingetragen", ""
    if typ == "jpeg":
        try:
            data = fetch_jpeg(url, cam["kamera_benutzer"], cam["kamera_passwort"], 10)
            return data, "OK", ""
        except Exception as e:  # noqa
            return None, http_error_text(e), str(e)
    if not FFMPEG.get("path"):
        return None, "ffmpeg fehlt - install.sh erneut ausführen", ""
    full = with_credentials(url, cam["kamera_benutzer"], cam["kamera_passwort"])
    try:
        r = subprocess.run(ffmpeg_args(cam, full, single=True), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "Zeitüberschreitung nach %d s - Kamera liefert kein Bild" % timeout, ""
    err = r.stderr.decode("utf-8", "replace").strip()
    err = err.replace(full, mask_url(full))
    if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8":
        return r.stdout, "OK", err
    return None, explain_ffmpeg_error(err) or "ffmpeg-Fehler (Code %d)" % r.returncode, err[-1500:]


def http_error_text(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return "Anmeldung abgelehnt (401) - Kamera-Benutzer/Passwort prüfen"
        if e.code == 404:
            return "Pfad nicht gefunden (404)"
        return "HTTP-Fehler %d" % e.code
    s = str(getattr(e, "reason", e))
    return explain_ffmpeg_error(s) or ("Fehler: %s" % s)


def fetch_jpeg(url, user, pw, timeout):
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    if user:
        pm.add_password(None, url, user, pw)
    opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(pm),
                                         urllib.request.HTTPDigestAuthHandler(pm))
    req = urllib.request.Request(url, headers={"User-Agent": "KlingelDashboard/" + APP_VERSION})
    with opener.open(req, timeout=timeout) as r:
        data = r.read(8 * 1024 * 1024)
    if data[:2] != b"\xff\xd8":
        raise ValueError("Antwort ist kein JPEG-Bild")
    return data


# ═══════════════════════════════════════════════════════════════════════════
#   Kamera-Worker
# ═══════════════════════════════════════════════════════════════════════════

class Camera(threading.Thread):
    def __init__(self, n):
        threading.Thread.__init__(self, daemon=True, name="cam%d" % n)
        self.n = n
        self.cfg = site_cfg(n)
        self.cond = threading.Condition()
        self.frame = None
        self.frame_id = 0
        self.frame_time = 0.0
        self.size = (0, 0)
        self.fps = 0.0
        self.stamps = []
        self.state = "ruht"
        self.message = ""
        self.detail = ""
        self.last_demand = 0.0
        self.proc = None
        self.stop_evt = threading.Event()
        self.clients = {}           # cid -> {"frames": n, "last": t}
        self.clients_lock = threading.Lock()

    # -- Zuschauer ----------------------------------------------------------
    def demand(self):
        self.last_demand = time.time()

    def wanted(self):
        c = self.cfg
        if c["kamera_typ"] == "aus" or not c["kamera_url"].strip():
            return False
        return c["immer_aktiv"] or (time.time() - self.last_demand) < CAM_LINGER_S

    def client_frame(self, cid):
        if not cid:
            return
        with self.clients_lock:
            e = self.clients.setdefault(cid, {"frames": 0, "last": 0.0})
            e["frames"] += 1
            e["last"] = time.time()

    def client_frames(self, cid):
        with self.clients_lock:
            now = time.time()
            for k in [k for k, v in self.clients.items() if now - v["last"] > 600]:
                del self.clients[k]
            e = self.clients.get(cid)
            return e["frames"] if e else 0

    def wait_frame(self, last_id, timeout):
        with self.cond:
            if self.frame_id == last_id or self.frame is None:
                self.cond.wait(timeout)
            if self.frame is None or self.frame_id == last_id:
                return None, last_id
            return self.frame, self.frame_id

    def _publish(self, data):
        now = time.time()
        with self.cond:
            self.stamps.append(now)
            while self.stamps and now - self.stamps[0] > 4.0:
                self.stamps.pop(0)
            span = now - self.stamps[0] if len(self.stamps) > 1 else 0
            self.fps = (len(self.stamps) - 1) / span if span >= 1.0 else 0.0
            self.frame = data
            self.frame_id += 1
            self.frame_time = now
            if self.frame_id % 25 == 1:
                self.size = jpeg_size(data)
            self.cond.notify_all()
        if self.state != "laeuft":
            self.state = "laeuft"
            self.message = ""
            self.detail = ""
            log("CAM%d" % self.n, "Bild empfangen (%dx%d)" % jpeg_size(data))

    def status(self):
        age = time.time() - self.frame_time if self.frame_time else None
        return {"state": self.state, "msg": self.message, "detail": self.detail,
                "fps": round(self.fps if self.state == "laeuft" else 0, 1),
                "w": self.size[0], "h": self.size[1],
                "age": round(age, 1) if age is not None else None,
                "typ": self.cfg["kamera_typ"]}

    # -- Ablauf -------------------------------------------------------------
    def run(self):
        backoff = 2.0
        while not self.stop_evt.is_set():
            if not self.wanted():
                if self.cfg["kamera_typ"] == "aus" or not self.cfg["kamera_url"].strip():
                    self.state, self.message = "aus", "keine Kamera eingetragen"
                else:
                    self.state, self.message = "ruht", ""
                self.fps = 0.0
                self.stop_evt.wait(0.3)
                backoff = 2.0
                continue
            ok = False
            try:
                if self.cfg["kamera_typ"] == "jpeg":
                    ok = self._run_jpeg()
                else:
                    ok = self._run_ffmpeg()
            except Exception as e:  # noqa
                self.state, self.message = "fehler", "interner Fehler: %s" % e
                log("CAM%d" % self.n, self.message)
            if self.stop_evt.is_set():
                break
            if ok:
                backoff = 2.0
            else:
                self.stop_evt.wait(backoff)
                backoff = min(backoff * 1.6, 15.0)

    def _run_ffmpeg(self):
        if not FFMPEG.get("path"):
            self.state, self.message = "fehler", "ffmpeg fehlt - install.sh erneut ausführen"
            self.stop_evt.wait(10)
            return False
        url = with_credentials(self.cfg["kamera_url"].strip(), self.cfg["kamera_benutzer"],
                               self.cfg["kamera_passwort"])
        args = ffmpeg_args(self.cfg, url)
        if self.state != "laeuft":
            self.state, self.message = "verbinde", "verbinde mit Kamera ..."
        log("CAM%d" % self.n, "starte ffmpeg: %s" % mask_url(url))
        err_lines = []
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.proc = proc

        def read_err():
            for line in iter(proc.stderr.readline, b""):
                s = line.decode("utf-8", "replace").strip()
                if s:
                    err_lines.append(s.replace(url, mask_url(url)))
                    del err_lines[:-15]
        threading.Thread(target=read_err, daemon=True).start()

        buf = bytearray()
        started = time.time()
        got_any = False
        last_frame = started
        fd = proc.stdout.fileno()
        try:
            while not self.stop_evt.is_set():
                r, _, _ = select.select([fd], [], [], 1.0)
                now = time.time()
                if r:
                    chunk = os.read(fd, 262144)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        s = buf.find(b"\xff\xd8")
                        if s < 0:
                            del buf[:-1]
                            break
                        e = buf.find(b"\xff\xd9", s + 2)
                        if e < 0:
                            if s:
                                del buf[:s]
                            if len(buf) > 8 * 1024 * 1024:
                                buf.clear()
                            break
                        self._publish(bytes(buf[s:e + 2]))
                        del buf[:e + 2]
                        got_any = True
                        last_frame = now
                if proc.poll() is not None and not r:
                    break
                if not got_any and now - started > CAM_FIRST_FRAME_S:
                    self.state = "fehler"
                    self.message = "kein Bild nach %d s - Kamera antwortet nicht" % CAM_FIRST_FRAME_S
                    break
                if got_any and now - last_frame > CAM_STALL_S:
                    self.state, self.message = "verbinde", "Bild steht seit %d s - verbinde neu" % CAM_STALL_S
                    break
                if not self.wanted():
                    break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            self.proc = None
        if self.stop_evt.is_set() or (not self.wanted() and got_any):
            return True
        err = "\n".join(err_lines)
        if err_lines:
            hint = explain_ffmpeg_error(err)
            self.state = "fehler"
            self.message = hint or err_lines[-1][:160]
            self.detail = err[-1200:]
            log("CAM%d" % self.n, "ffmpeg: %s" % (err_lines[-1][:200]))
        elif proc.returncode not in (0, None) and self.state != "fehler":
            self.state, self.message = "fehler", "ffmpeg beendet (Code %s)" % proc.returncode
        if self.state == "laeuft":
            self.state, self.message = "verbinde", "Stream unterbrochen - verbinde neu"
        return got_any

    def _run_jpeg(self):
        url = self.cfg["kamera_url"].strip()
        interval = 1.0 / max(1, self.cfg["bilder_pro_sekunde"])
        if self.state != "laeuft":
            self.state, self.message = "verbinde", "lade Standbild ..."
        fails = 0
        got = False
        while not self.stop_evt.is_set() and self.wanted():
            t0 = time.time()
            try:
                self._publish(fetch_jpeg(url, self.cfg["kamera_benutzer"], self.cfg["kamera_passwort"], 8))
                got = True
                fails = 0
            except Exception as e:  # noqa
                fails += 1
                if fails >= 3:
                    self.state, self.message = "fehler", http_error_text(e)
                    self.detail = str(e)
                    return got
            self.stop_evt.wait(max(0.05, interval - (time.time() - t0)))
        return True

    def stop(self):
        self.stop_evt.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass


CAMERAS = {}


# ═══════════════════════════════════════════════════════════════════════════
#   Netzwerk-Infos, Firewall
# ═══════════════════════════════════════════════════════════════════════════

def local_ips():
    ips = []
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=5).stdout.decode()
        for line in out.splitlines():
            m = re.search(r"^\d+:\s+(\S+)\s+inet\s+([\d.]+)/", line)
            if m and not m.group(2).startswith("127."):
                ips.append({"dev": m.group(1), "ip": m.group(2)})
    except Exception:  # noqa
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))
            ips.append({"dev": "?", "ip": s.getsockname()[0]})
            s.close()
        except OSError:
            pass
    return ips


def all_ports():
    return [CFG["dashboard%d.port" % n] for n in range(1, NUM_SITES + 1)] + [CFG["allgemein.einrichtung_port"]]


def sync_firewall():
    """Legt in OpenWrt eine Firewall-Regel für die Ports an (Zugriff auch über WAN)."""
    uci = shutil.which("uci")
    if not uci or not os.path.exists("/etc/config/firewall"):
        return
    name = "klingel_dashboard"

    def run(*a):
        return subprocess.run([uci] + list(a), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=10).stdout.decode().strip()
    try:
        if not CFG["allgemein.firewall_freigeben"]:
            if run("-q", "get", "firewall.%s" % name):
                run("delete", "firewall.%s" % name)
                run("commit", "firewall")
                subprocess.run(["/etc/init.d/firewall", "reload"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60)
                log("FW", "Firewall-Regel entfernt")
            return
        want = " ".join(str(p) for p in all_ports())
        if run("-q", "get", "firewall.%s" % name) == "rule" and \
                run("-q", "get", "firewall.%s.dest_port" % name) == want:
            return
        run("set", "firewall.%s=rule" % name)
        run("set", "firewall.%s.name=Klingel-Dashboard" % name)
        run("set", "firewall.%s.src=wan" % name)
        run("set", "firewall.%s.proto=tcp" % name)
        run("set", "firewall.%s.dest_port=%s" % (name, want))
        run("set", "firewall.%s.target=ACCEPT" % name)
        run("commit", "firewall")
        subprocess.run(["/etc/init.d/firewall", "reload"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60)
        log("FW", "Firewall-Regel gesetzt: TCP %s (WAN)" % want)
    except Exception as e:  # noqa
        log("FW", "Firewall konnte nicht angepasst werden: %s" % e)


# ═══════════════════════════════════════════════════════════════════════════
#   HTTP
# ═══════════════════════════════════════════════════════════════════════════

MQTT = None
SERVERS = []
RESTART_LOCK = threading.Lock()
RESTART_PENDING = [False]
TEMPLATES = {}


def template(name):
    p = os.path.join(WEB_DIR, name)
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


def site_client_config(n):
    sc = site_cfg(n)
    return {
        "site": n, "title": sc["titel"] or ("Dashboard %d" % n), "version": APP_VERSION,
        "repeat_ms": CFG["oeffner.wiederholung_ms"],
        "cam": sc["kamera_typ"] != "aus" and bool(sc["kamera_url"].strip()),
        "bildmodus": sc["bildmodus"], "fps": sc["bilder_pro_sekunde"],
        "bells": [{"id": b["id"], "name": b["name"]} for b in site_bells(n)],
    }


def bells_state(n):
    now = time.time()
    out = {}
    with BELL_LOCK:
        for b in site_bells(n):
            k = (n, b["id"])
            out[str(b["id"])] = {"n": BELL_COUNT.get(k, 0), "a": BELL_UNTIL.get(k, 0) > now}
    return out


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, role, site=0):
        self.role = role
        self.site = site
        HTTPServer.__init__(self, addr, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "KlingelDashboard/" + APP_VERSION
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    # -- Antworten ----------------------------------------------------------
    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 200000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return {}

    def _query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))

    def _route(self):
        return urllib.parse.urlsplit(self.path).path

    # -- Kamera -------------------------------------------------------------
    def _snapshot(self, cam):
        cam.demand()
        frame = cam.frame
        if frame is None or time.time() - cam.frame_time > 15:
            frame, _ = cam.wait_frame(cam.frame_id if frame is not None else 0, 8)
        if frame is None:
            return self._send(503, "Kein Kamerabild: %s" % (cam.message or cam.state))
        cam.client_frame(self._query().get("cid", ""))
        self._send(200, frame, "image/jpeg")

    def _mjpeg(self, cam):
        cid = self._query().get("cid", "")
        cam.demand()
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=klingelbild")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        last = 0
        idle = 0.0
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while not RESTART_PENDING[0]:
                frame, fid_ = cam.wait_frame(last, 2.0)
                cam.demand()
                if frame is None:
                    idle += 2.0
                    if idle > 120:
                        break
                    continue
                idle = 0.0
                last = fid_
                self.wfile.write(b"--klingelbild\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                self.wfile.flush()
                cam.client_frame(cid)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass

    # -- Auth ---------------------------------------------------------------
    def _auth_ok(self):
        pw = CFG["allgemein.admin_passwort"]
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                dec = base64.b64decode(h[6:]).decode("utf-8", "replace")
                if dec.split(":", 1)[-1] == pw:
                    return True
            except ValueError:
                pass
        self._send(401, "Anmeldung erforderlich", extra={
            "WWW-Authenticate": 'Basic realm="Klingel Einrichtung", charset="UTF-8"'})
        return False

    # -- Routing ------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if self.server.role == "site":
                self._site_get(self.server.site)
            else:
                if self._auth_ok():
                    self._setup_get()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            if self.server.role == "site":
                self._site_post(self.server.site)
            else:
                if self._auth_ok():
                    self._setup_post()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _site_get(self, n):
        p = self._route()
        cam = CAMERAS[n]
        if p in ("/", "/index.html"):
            cfg = site_client_config(n)
            html = template("dashboard.html")
            html = html.replace("{{TITLE}}", _html_escape(cfg["title"]))
            html = html.replace("{{VERSION}}", APP_VERSION)
            html = html.replace("{{CONFIG_JSON}}", json.dumps(cfg, ensure_ascii=True).replace("</", "<\\/"))
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/stream.mjpg":
            return self._mjpeg(cam)
        if p == "/snapshot.jpg":
            return self._snapshot(cam)
        if p == "/api/config":
            return self._json(site_client_config(n))
        if p == "/api/poll":
            q = self._query()
            st = cam.status()
            st["client_frames"] = cam.client_frames(q.get("cid", ""))
            if q.get("view") == "1":
                cam.demand()
            return self._json({"mqtt": bool(MQTT and MQTT.connected), "bells": bells_state(n), "cam": st,
                               "t": round(time.time(), 2)})
        if p in ("/api/press", "/api/release", "/mqtt/press", "/mqtt/release"):
            return self._site_post(n)
        if p == "/favicon.ico":
            return self._send(204, b"")
        self._send(404, "Nicht gefunden")

    def _site_post(self, n):
        p = self._route()
        if p in ("/api/press", "/mqtt/press"):
            ok = MQTT.publish(CFG["oeffner.topic_druecken"], CFG["oeffner.payload_druecken"])
            return self._json({"ok": ok, "mqtt": MQTT.connected})
        if p in ("/api/release", "/mqtt/release"):
            ok = True
            if CFG["oeffner.topic_loslassen"]:
                ok = MQTT.publish(CFG["oeffner.topic_loslassen"], CFG["oeffner.payload_loslassen"])
            return self._json({"ok": ok, "mqtt": MQTT.connected})
        self._send(404, "Nicht gefunden")

    def _setup_get(self):
        p = self._route()
        if p in ("/", "/index.html"):
            html = template("setup.html").replace("{{VERSION}}", APP_VERSION)
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/api/schema":
            return self._json({"fields": SCHEMA, "sections": SECTION_TITLES, "num_sites": NUM_SITES,
                               "num_bells": NUM_BELLS})
        if p == "/api/settings":
            out = {}
            for f in SCHEMA:
                v = CFG[fid(f)]
                if f["type"] == "pass":
                    out[fid(f)] = ""
                    out[fid(f) + "__set"] = bool(v)
                else:
                    out[fid(f)] = v
            return self._json(out)
        if p == "/api/status":
            return self._json(system_status())
        m = re.match(r"^/cam/(\d+)/(stream\.mjpg|snapshot\.jpg)$", p)
        if m and int(m.group(1)) in CAMERAS:
            cam = CAMERAS[int(m.group(1))]
            return self._mjpeg(cam) if m.group(2) == "stream.mjpg" else self._snapshot(cam)
        if p == "/favicon.ico":
            return self._send(204, b"")
        self._send(404, "Nicht gefunden")

    def _setup_post(self):
        p = self._route()
        data = self._body_json()
        if p == "/api/settings":
            new, err = validate_settings(data)
            if err:
                return self._json({"ok": False, "error": err}, 400)
            try:
                save_config(new)
            except OSError as e:
                return self._json({"ok": False, "error": "Speichern fehlgeschlagen: %s" % e}, 500)
            log("CFG", "Einstellungen gespeichert - Neustart")
            self._json({"ok": True, "restart": True})
            schedule_restart()
            return
        if p == "/api/test_cam":
            n = int(data.get("site") or 1)
            vals = data.get("values") or {}
            cam = {}
            for f in SCHEMA:
                if f["sec"] != "dashboard%d" % n:
                    continue
                k = fid(f)
                v = vals.get(k, CFG[k])
                if f["type"] == "pass" and v == "" and not vals.get(k + "__clear"):
                    v = CFG[k]
                try:
                    cam[f["key"]] = coerce(f, v)
                except ValueError as e:
                    return self._json({"ok": False, "error": str(e), "log": ""})
            jpg, msg, logtxt = grab_single_frame(cam)
            if jpg:
                w, h = jpeg_size(jpg)
                return self._json({"ok": True, "image": base64.b64encode(jpg).decode(), "w": w, "h": h,
                                   "log": logtxt})
            return self._json({"ok": False, "error": msg, "log": logtxt})
        if p == "/api/test_bell":
            n, b = int(data.get("site") or 0), int(data.get("bell") or 0)
            if 1 <= n <= NUM_SITES and 1 <= b <= NUM_BELLS:
                ring(n, b, "Test")
                return self._json({"ok": True})
            return self._json({"ok": False}, 400)
        if p == "/api/restart":
            self._json({"ok": True})
            schedule_restart()
            return
        self._send(404, "Nicht gefunden")


def _html_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def validate_settings(data):
    new = dict(CFG)
    errors = []
    for f in SCHEMA:
        k = fid(f)
        if k not in data:
            continue
        v = data[k]
        if f["type"] == "pass":
            if data.get(k + "__clear"):
                new[k] = ""
                continue
            if v in ("", None):
                continue
        try:
            new[k] = coerce(f, v)
        except ValueError as e:
            errors.append(str(e))
    ports = [new["dashboard%d.port" % n] for n in range(1, NUM_SITES + 1)] + [new["allgemein.einrichtung_port"]]
    if len(set(ports)) != len(ports):
        errors.append("Die Ports der Dashboards und der Einrichtungsseite müssen verschieden sein")
    reserved = {22: "SSH", 53: "DNS", 80: "GL.iNet-Oberfläche", 443: "GL.iNet-Oberfläche",
                1883: "MQTT-Broker", 67: "DHCP"}
    current = set(all_ports())
    for p in ports:
        if p in reserved:
            errors.append("Port %d ist belegt (%s)" % (p, reserved[p]))
        elif p not in current and not port_free(p):
            errors.append("Port %d wird schon von einem anderen Programm benutzt" % p)
    if not new["oeffner.topic_druecken"]:
        errors.append("Topic beim Drücken darf nicht leer sein")
    for n in range(1, NUM_SITES + 1):
        u = new["dashboard%d.kamera_url" % n].strip().lower()
        t = new["dashboard%d.kamera_typ" % n]
        if t == "jpeg" and u and not u.startswith(("http://", "https://")):
            errors.append("Dashboard %d: Standbild-URL muss mit http:// beginnen" % n)
    return new, ("; ".join(errors) if errors else "")


def system_status():
    return {
        "name": APP_NAME, "version": APP_VERSION, "uptime_s": int(time.time() - START_TIME),
        "mqtt": bool(MQTT and MQTT.connected), "mqtt_state": MQTT.state if MQTT else "-",
        "ffmpeg": FFMPEG, "ips": local_ips(), "ports": all_ports(),
        "cams": {str(n): CAMERAS[n].status() for n in CAMERAS},
        "titles": {str(n): CFG["dashboard%d.titel" % n] for n in range(1, NUM_SITES + 1)},
        "python": sys.version.split()[0], "config": CONFIG_PATH,
    }


# ═══════════════════════════════════════════════════════════════════════════
#   Start, Neustart, Ende
# ═══════════════════════════════════════════════════════════════════════════

def shutdown_children():
    for c in CAMERAS.values():
        c.stop()
    for c in CAMERAS.values():
        p = c.proc
        if p and p.poll() is None:
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()


def schedule_restart():
    with RESTART_LOCK:
        if RESTART_PENDING[0]:
            return
        RESTART_PENDING[0] = True

    def do():
        time.sleep(0.8)
        log("SYS", "Neustart ...")
        if MQTT:
            MQTT.stop()
        shutdown_children()
        for s in SERVERS:
            try:
                s.server_close()
            except OSError:
                pass
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, "-u"] + sys.argv)
    threading.Thread(target=do, daemon=True).start()


def on_signal(signum, frame):
    log("SYS", "Beende (Signal %d)" % signum)
    shutdown_children()
    os._exit(0)


def main():
    global MQTT
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log("SYS", "%s v%s startet (Python %s)" % (APP_NAME, APP_VERSION, sys.version.split()[0]))
    log("SYS", "Konfiguration: %s" % CONFIG_PATH)
    find_ffmpeg()

    for n in range(1, NUM_SITES + 1):
        CAMERAS[n] = Camera(n)
        CAMERAS[n].start()

    MQTT = MQTTClient(on_mqtt_message)
    MQTT.start()

    plan = [(CFG["dashboard%d.port" % n], "site", n) for n in range(1, NUM_SITES + 1)]
    plan.append((CFG["allgemein.einrichtung_port"], "setup", 0))
    for port, role, n in plan:
        for attempt in range(10):
            try:
                srv = Server(("0.0.0.0", port), role, n)
                break
            except OSError as e:
                if attempt == 9:
                    log("HTTP", "Port %d nicht nutzbar: %s" % (port, e))
                    srv = None
                else:
                    time.sleep(1)
        if srv:
            SERVERS.append(srv)
            threading.Thread(target=srv.serve_forever, daemon=True, name="http%d" % port).start()

    threading.Thread(target=sync_firewall, daemon=True).start()

    ips = [i["ip"] for i in local_ips()] or ["<IP>"]
    log("SYS", "=" * 58)
    for ip in ips:
        for n in range(1, NUM_SITES + 1):
            log("SYS", "Dashboard %d:  http://%s:%d   (%s)" % (n, ip, CFG["dashboard%d.port" % n],
                                                             CFG["dashboard%d.titel" % n]))
        log("SYS", "Einrichtung:  http://%s:%d" % (ip, CFG["allgemein.einrichtung_port"]))
    log("SYS", "=" * 58)

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
