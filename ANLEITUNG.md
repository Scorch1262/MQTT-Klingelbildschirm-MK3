# Klingel-Dashboard Brume 2 – v4.3.0

Klingel-Dashboard für den **GL.iNet Brume 2 (GL-MT2500)**. Es läuft im Autostart der
Brume und ersetzt den PC (v2.x) bzw. das RP2350-Board (v3.x):

| Port (Standard) | Seite        | Inhalt |
|-----------------|--------------|--------|
| **8081**        | Dashboard 1  | Kamerabild, Klingel-Symbol, Öffner-Taste |
| **8082**        | Dashboard 2  | gleiche Oberfläche, **dasselbe Kamerabild**, eigenes Klingel-Topic |
| **8083**        | Einrichtung  | Broker, Öffner, Topics, Kameras, Ports, Kameratest |

* Beide Dashboards senden beim Drücken der Öffnen-Taste **denselben MQTT-Befehl an
  denselben Broker** (wiederholt, solange gedrückt; beim Loslassen der Loslassen-Befehl).
* Jedes Dashboard klingelt auf **genau einem eigenen Topic** (z. B. Dashboard 1 auf
  `doorbell/bell1`, Dashboard 2 auf `doorbell/bell2`; `+`/`#` erlaubt, leere Payload =
  jede Nachricht auf dem Topic). Der Klingelton startet ohne „Tippen zum Starten“.
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

1. Die Datei `klingel-dashboard-brume2_v4.3.0.sh` auf die Brume kopieren,
   z. B. mit WinSCP (Protokoll SCP, Benutzer `root`) nach `/root/` oder per
   ```
   scp -O klingel-dashboard-brume2_v4.3.0.sh root@<IP-der-Brume>:/root/
   ```
2. Per SSH auf der Brume anmelden und starten:
   ```
   ssh root@<IP-der-Brume>
   sh /root/klingel-dashboard-brume2_v4.3.0.sh
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

Es gibt **eine Kamera (einen RTSP-Stream)**, die auf **beiden Dashboards** angezeigt wird.
ffmpeg holt den Stream nur einmal ab und verteilt die Bilder an alle geöffneten Seiten.


* **Kamera-URL:** dieselbe wie in VLC, z. B. `rtsp://192.168.1.200:554/stream2`.
  Benutzer und Passwort am besten in die eigenen Felder eintragen – Sonderzeichen
  wie `@ # : /` im Passwort werden dann richtig behandelt.
* **Substream nehmen** (z. B. 640×360 oder 1280×720). Die Brume muss jedes Bild
  dekodieren; ein 4K- oder 1080p-Hauptstream mit 25 B/s belastet ihre CPU stark.
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

## Außentemperatur

Oben rechts im Dashboard steht die aktuelle Außentemperatur mit Wettersymbol und Ort.
Die Daten kommen von **open-meteo.com** (kostenlos, ohne Anmeldung oder API-Schlüssel),
die Brume fragt sie alle 10 Minuten ab – die iPads selbst brauchen kein Internet.

Einrichtung (Port 8083 → Karte „Außentemperatur“):

* **Ort:** Ortsname oder Postleitzahl, z. B. `Hamburg`, `20095` oder `Musterstadt, DE`
  (mit Ländercode, wenn es den Namen mehrfach gibt)
* oder **Breiten- und Längengrad** (genauer, z. B. aus Google Maps: Rechtsklick auf den Ort)
* **Ort und Temperatur prüfen** zeigt sofort, welcher Ort gefunden wurde und die Temperatur.

Beim Antippen bzw. Darüberfahren zeigt die Anzeige zusätzlich Wetterlage, gefühlte
Temperatur und Tagesminimum/-maximum. Ist das Internet weg, bleibt der letzte Wert stehen
und wird nach drei Intervallen grau dargestellt.

## Dauerbetrieb auf den beiden iPads (6. Generation)

Die Seiten sind für den Dauerbetrieb auf einem iPad im Querformat (1024×768) ausgelegt.

1. Seite in Safari öffnen (`http://<IP-der-Brume>:8081` bzw. `:8082`) →
   Teilen → **Zum Home-Bildschirm**. Vom Home-Bildschirm gestartet läuft sie im Vollbild.
2. **Einstellungen → Anzeige & Helligkeit → Automatische Sperre → Nie**, iPad am Netzteil.
3. **Einstellungen → Bedienungshilfen → Geführter Zugriff** einschalten und in der Seite
   dreimal die Home-Taste drücken – dann bleibt das iPad fest auf dem Dashboard.
4. Nach dem Öffnen **einmal irgendwo auf die Seite tippen**. Safari lässt Ton erst nach
   einer Berührung zu (das lässt sich auf dem iPad nicht abschalten). Solange der Ton
   gesperrt ist, ist der AUDIO-Punkt rot und unten im Bild blinkt der Knopf
   **„Klingelton einschalten – hier tippen“**. Nach dem Tippen klingelt es einmal zur Probe.
   Klappt die Freigabe nicht, steht der Grund im Ereignis-Log und in
   `/root/Klingel-Dashboard/logs/klingel.log` (Zeilen mit `[IPAD1]`/`[IPAD2]`). Danach bleibt der Ton frei,
   solange die Seite offen ist; die Seite lädt sich dafür nie selbst neu.
5. Lautstärke hoch, Lautlos-Schalter aus.
6. **Blockierungsmodus (Lockdown Mode):** Ist er auf dem iPad an, schaltet Safari Web Audio
   und WAV-Ton ab. Das Dashboard spielt den Klingelton dann als AAC/MP3 – das reicht.
   Wer Web Audio zusätzlich möchte: in Safari auf „Aa“ bzw. das Seitenmenü tippen →
   Website-Einstellungen → Blockierungsmodus für diese Website ausschalten.

Damit das Bild über Tage stabil bleibt, verbindet die Seite den Videostrom alle
20 Minuten unauffällig neu und bei Aussetzern sofort.

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
| `GET /cam/snapshot.jpg` | Vorschaubild |

---

## Versionsverlauf

* **v4.3.0** – aktuelle Außentemperatur
  * Temperatur, Wettersymbol und Ort in der Kopfzeile beider Dashboards
  * Daten von Open-Meteo (ohne API-Schlüssel), Abruf durch die Brume alle 10 min
  * Ort per Name/Postleitzahl (automatische Suche) oder Koordinaten, Test-Knopf
  * Abruf über Python-HTTPS, ersatzweise curl/wget; Installer ergänzt python3-openssl

* **v4.2.4** – Klingelton als AAC/MP3
  * Safari lehnte den WAV-Ton ab (Code 4) und Web Audio fehlte – typisch für den
    Blockierungsmodus (Lockdown Mode). Die Brume erzeugt den Klingelton jetzt mit ffmpeg
    zusätzlich als AAC (m4a) und MP3; das iPad nimmt das erste Format, das es abspielen kann
  * Diagnosezeile im Protokoll: Web Audio vorhanden?, unterstützte Tonformate

* **v4.2.3** – Tondatei auf dem iPad
  * Safari meldete „NotSupportedError“: sein Media-Player lehnte die Tondatei vom
    HTTP-Server ab. Der Klingelton wird jetzt vorab geladen und als Blob abgespielt;
    Teilantworten (Range) kommen zusätzlich als HTTP/1.1
  * Protokoll meldet auch Erfolg („Datei-Ton freigegeben“, „WebAudio aktiv“),
    gleiche Meldungen nur noch einmal

* **v4.2.2** – Ton-Freigabe auf dem iPad
  * echter Knopf „Klingelton einschalten“ im Bild, klingelt zur Bestätigung einmal
  * Web Audio wird erst beim Tippen angelegt (iOS-Vorgabe), bei Bedarf neu
  * Freigabe nur über echte Gesten (touchend/click), touchstart zählt auf iOS nicht
  * Audio-Fehler der iPads werden mit Grund in logs/klingel.log geschrieben

* **v4.2.1** – Klingelton auf dem iPad
  * Klingelton zusätzlich als Datei `klingel.wav` vom Brume-Server (mit Byte-Range,
    wie Safari es für Audio verlangt) – auf iOS zuverlässiger als reines Web Audio
  * Freischalten bei der ersten Berührung (touchend/click), Web Audio als Ersatz
  * gut sichtbarer Hinweis im Kamerabild, solange der Ton gesperrt ist
  * Tippen auf „AUDIO“ oben spielt den Klingelton zum Test
  * Audio-Zustand und JavaScript-Fehler erscheinen im Ereignis-Log

* **v4.2.0** – ein Klingel-Topic je Dashboard, Dauerbetrieb auf iPad (6. Gen.)
  * je Webseite genau ein Klingel-Signal (Topic + Payload), ein Klingel-Symbol
  * Hinweis „TON AUS – BITTE ANTIPPEN“, solange Safari den Ton sperrt
  * Videostrom wird alle 20 min neu verbunden (stabil im Dauerbetrieb)
  * veraltete Einträge in der config.ini werden entfernt

* **v4.1.0** – eine Kamera für beide Dashboards
  * nur noch ein RTSP-Stream (Abschnitt `[kamera]` in der config.ini), ein ffmpeg-Prozess
  * Einrichtungsseite mit einer Kamerakarte, Dashboard-Karten nur noch Port, Titel, Klingeln
  * alte config.ini: die Kamera von Dashboard 1 wird automatisch übernommen

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
