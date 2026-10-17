# Klingel-Dashboard Brume 2 – v4.0.1

Klingel-Dashboard für den **GL.iNet Brume 2 (GL-MT2500)**. Es läuft im Autostart der
Brume und ersetzt den PC (v2.x) bzw. das RP2350-Board (v3.x):

| Port (Standard) | Seite        | Inhalt |
|-----------------|--------------|--------|
| **8081**        | Dashboard 1  | Kamerabild, Klingel-Symbole, Öffner-Taste |
| **8082**        | Dashboard 2  | gleiche Oberfläche, eigene Kamera, eigene Klingel-Topics |
| **8083**        | Einrichtung  | Broker, Öffner, Topics, Kameras, Ports, Kameratest |

* Beide Dashboards senden beim Drücken der Öffnen-Taste **denselben MQTT-Befehl an
  denselben Broker** (wiederholt, solange gedrückt; beim Loslassen der Loslassen-Befehl).
* Jedes Dashboard reagiert auf **eigene Klingel-Topics** (bis zu 3 Symbole, `+`/`#` erlaubt,
  leere Payload = jede Nachricht). Der Klingelton startet ohne „Tippen zum Starten“.
* Läuft auch auf dem **iPad mini 1 (iOS 9)**: reines ES5-JavaScript, Kamerabild als MJPEG.
* Port 80/443 bleiben frei für die GL.iNet-Oberfläche.

---

## Warum es jetzt ein Kamerabild gibt

Browser können RTSP nicht abspielen, das H.264-Video muss vorher umgewandelt werden.

* **RP2350 (v3.x):** Das Board kann H.264 nicht umwandeln. v3.1 hat den Stream
  roh an den Browser geschickt und dort mit *jmuxer* abgespielt. jmuxer braucht
  *Media Source Extensions* – die gibt es auf dem iPad mini 1 (iOS 9) nicht. Dazu kam
  die Fehlermeldung „Kamera antwortet nicht“ schon beim RTSP-Verbindungsaufbau.
* **Brume 2 (v4.0):** Hier wandelt **ffmpeg** auf der Brume den RTSP-Stream in
  MJPEG um – wie damals auf dem PC (v2.x). Ein MJPEG-Bild zeigt jeder Browser an,
  auch Safari auf iOS 9. ffmpeg baut die RTSP-Verbindung genauso auf wie VLC.
* **Wichtig:** Das `ffmpeg` aus den OpenWrt-Paketquellen ist **ohne H.264-Decoder**
  gebaut (Patent-Option ist dort abgeschaltet). Der Installer lädt deshalb ein
  statisch gebautes ffmpeg (johnvansickle.com, ARM64) nach
  `/root/Klingel-Dashboard/bin/ffmpeg`. Dieses kann auch H.265.

Kommt im Browser trotzdem kein Video an, wechselt das Dashboard automatisch auf
**Einzelbilder** (`/snapshot.jpg`, mehrere pro Sekunde).

---

## Installation

1. Die Datei `klingel-dashboard-brume2_v4.0.1.sh` auf die Brume kopieren,
   z. B. mit WinSCP (Protokoll SCP, Benutzer `root`) nach `/root/` oder per
   ```
   scp -O klingel-dashboard-brume2_v4.0.1.sh root@<IP-der-Brume>:/root/
   ```
2. Per SSH auf der Brume anmelden und starten:
   ```
   ssh root@<IP-der-Brume>
   sh /root/klingel-dashboard-brume2_v4.0.1.sh
   ```
3. Der Installer
   * installiert bei Bedarf **python3** (`opkg`),
   * kopiert das Programm nach `/root/Klingel-Dashboard`,
   * lädt **ffmpeg mit H.264** (ca. 25 MB),
   * richtet den **Autostart** ein (`/etc/init.d/klingel-dashboard`, startet nach jedem
     Neustart und nach Abstürzen automatisch neu),
   * trägt den Ordner in `/etc/sysupgrade.conf` ein (bleibt bei Firmware-Updates erhalten),
   * zeigt am Ende die Adressen der Dashboards.
4. Einrichtung im Browser öffnen: `http://<IP-der-Brume>:8083`
   → Broker, Öffner-Topics, Kamera-URLs eintragen → **Kamera mit diesen Werten testen**
   → **Speichern & Neustart**.

**Update:** neue Paketdatei genauso ausführen. Die `config.ini` bleibt erhalten.

### Alles in einem Ordner

Nach der Installation liegt alles in `/root/Klingel-Dashboard`, neben den anderen
Programmen (z. B. `Outfit-Dashboard`, `mqtt-dashboard`):

```
/root/Klingel-Dashboard/
├── klingel_server.py        Programm
├── config.ini               Einstellungen (lesbar, von Hand änderbar)
├── web/                     Dashboard- und Einrichtungsseite
├── bin/ffmpeg               ffmpeg mit H.264/H.265
├── logs/klingel.log         Betriebsprotokoll (max. 256 KB, dann klingel.log.1)
├── logs/install.log         Protokoll der letzten Installation
├── files/klingel-dashboard.init   Autostart-Skript
├── paket/                   das ausgeführte Installationspaket (wird hierher verschoben)
├── install.sh  uninstall.sh  ANLEITUNG.md  VERSION
```

Außerhalb des Ordners gibt es nur den Verweis `/etc/init.d/klingel-dashboard`
→ `files/klingel-dashboard.init`. OpenWrt startet Dienste nur von dort, deshalb ist
er für den Autostart nötig. Die Version 4.0.0 hieß noch `Klingel-Dashboard-Brume2`;
der Installer übernimmt `config.ini` und ffmpeg daraus und entfernt den alten Ordner.

**Brume ohne Internet:** `ffmpeg-release-arm64-static.tar.xz` von
<https://johnvansickle.com/ffmpeg/> auf dem PC laden und in denselben Ordner wie die
Paketdatei (oder nach `/root/Klingel-Dashboard/paket/`) legen. Der Installer nimmt
dann das lokale Archiv.

### Firewall

Die Brume läuft als Netzwerkteilnehmer über LAN- und WAN-Port. Damit die Dashboards
auch über den **WAN-Port** erreichbar sind, legt das Programm eine Firewall-Regel
`Klingel-Dashboard` für die drei Ports an (abschaltbar auf der Einrichtungsseite).

---

## Bedienung im Alltag

| Befehl (SSH)                                  | Wirkung |
|-----------------------------------------------|---------|
| `/etc/init.d/klingel-dashboard restart`       | Dienst neu starten |
| `/etc/init.d/klingel-dashboard stop` / `start`| anhalten / starten |
| `tail -f /root/Klingel-Dashboard/logs/klingel.log` | Protokoll ansehen (Kamera-, MQTT-, Klingelmeldungen) |
| `sh /root/Klingel-Dashboard/uninstall.sh` | Autostart und Firewall-Regel entfernen (Ordner bleibt) |
| `sh /root/Klingel-Dashboard/uninstall.sh --alles` | zusätzlich den ganzen Ordner löschen |

Die Einstellungen stehen lesbar in `/root/Klingel-Dashboard/config.ini`.
Nach einer Änderung von Hand: `/etc/init.d/klingel-dashboard restart`.

---

## Kamera einrichten

* **Kamera-URL:** dieselbe wie in VLC, z. B. `rtsp://192.168.1.200:554/stream2`.
  Benutzer und Passwort am besten in die eigenen Felder eintragen – Sonderzeichen
  wie `@ # : /` im Passwort werden dann richtig behandelt.
* **Substream nehmen** (z. B. 640×360 oder 1280×720). Die Brume muss jedes Bild
  dekodieren; ein 4K- oder 1080p-Hauptstream mit 25 B/s belastet ihre CPU stark,
  bei zwei Kameras doppelt.
* **Bilder pro Sekunde** (Standard 8), **maximale Breite** (960) und
  **JPEG-Qualität** (75 %) bestimmen Last und Datenmenge fürs iPad.
* **Sparmodus:** nur Schlüsselbilder dekodieren – sehr wenig CPU, dafür meist nur
  etwa 1 Bild pro Sekunde.
* Die Kamera wird nur abgerufen, solange ein Dashboard sie anzeigt (+30 s).
  Mit **Kamera dauerhaft abrufen** liegt beim Klingeln sofort ein Bild bereit.
* **Kameraquelle `jpeg`:** statt RTSP eine Standbild-URL der Kamera
  (`http://…/snapshot.jpg`), braucht kein ffmpeg.

### Meldungen im Kamerabild

| Meldung | Bedeutung |
|---------|-----------|
| Anmeldung abgelehnt | Kamera-Benutzer/Passwort falsch |
| Pfad nicht gefunden (404/454) | Stream-Pfad in der URL falsch |
| Verbindung abgelehnt | falscher Port oder RTSP in der Kamera aus |
| Zeitüberschreitung / nicht erreichbar | IP falsch oder Kamera nicht im selben Netz wie die Brume |
| Transport passt nicht | RTSP-Transport auf `udp` bzw. `tcp` umstellen |
| ffmpeg ohne H.264-Decoder | Installer erneut ausführen |
| Video kommt nicht an – Einzelbildmodus | Browser zeigt MJPEG nicht an, Dashboard nutzt Einzelbilder |

Die vollständige ffmpeg-Ausgabe zeigt der Knopf **Kamera mit diesen Werten testen**.

---

## Audio

Der Klingelton wird im Browser erzeugt und startet automatisch. Wo der Browser Ton
ohne Berührung blockiert (Safari auf dem iPad), gibt die **erste beliebige Berührung**
den Ton unsichtbar frei – ohne Overlay. Der grüne **AUDIO**-Punkt zeigt, dass er aktiv
ist. Für Ton bei gesperrtem iPad: Lautlos-Schalter aus, Seite im Vordergrund lassen
(Auto-Sperre am besten auf „Nie“).

---

## HTTP-Schnittstelle

| Dashboard (8081/8082) | |
|---|---|
| `GET /` | Dashboard |
| `GET /stream.mjpg` | Kamerabild als MJPEG |
| `GET /snapshot.jpg` | aktuelles Einzelbild |
| `GET /api/poll` | Klingel-Zähler, MQTT- und Kamerastatus |
| `POST /api/press`, `POST /api/release` | Öffner-Befehl senden |

| Einrichtung (8083) | |
|---|---|
| `GET/POST /api/settings` | Einstellungen lesen/speichern (danach Neustart) |
| `GET /api/status` | Version, IPs, MQTT, ffmpeg, Kameras |
| `POST /api/test_cam` | Kamera einmalig testen |
| `POST /api/test_bell` | Testklingeln (ohne MQTT) |
| `GET /cam/1/snapshot.jpg` | Vorschaubild |

---

## Versionsverlauf

* **v4.0.1** – alles in einem Ordner `/root/Klingel-Dashboard`
  * Ordner wird als Erstes angelegt (auch bei Abbruch sichtbar, mit `logs/install.log`)
  * Betriebsprotokoll `logs/klingel.log`, Autostart-Skript als Verweis aus dem Ordner
  * Installationspaket wird nach `paket/` verschoben, `uninstall.sh --alles`

* **v4.0.0** – Version für GL.iNet Brume 2 (Python, nur Standardbibliothek)
  * Kamerabild über ffmpeg → MJPEG (iOS-9-tauglich), automatischer Einzelbild-Rückfall
  * statisches ffmpeg mit H.264/H.265, da das OpenWrt-Paket kein H.264 kann
  * klare Fehlermeldungen der Kamera, Kameratest mit Vorschau auf der Einrichtungsseite
  * Autostart über procd, Firewall-Regel, bleibt bei Firmware-Updates erhalten
  * zwei Dashboards (8081/8082), gemeinsamer Öffner, getrennte Klingel-Topics,
    Einrichtung auf 8083, Audio ohne „Tippen zum Starten“
* v3.1.0 – RP2350-MINI(ETH), direkter RTSP-Client (kein Bild)
* v3.0.0 – RP2350-MINI(ETH), Kamera nur über externe URL
* v2.3.1 – Python/Windows-Version mit ffmpeg
