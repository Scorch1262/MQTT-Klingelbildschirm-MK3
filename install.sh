#!/bin/sh
# ════════════════════════════════════════════════════════════════════
#  Klingel-Dashboard Brume 2 – Installer v4.2.3
#  für GL.iNet Brume 2 (GL-MT2500, OpenWrt / GL-Firmware 4.x)
#
#  Alles liegt danach in EINEM Ordner:  /root/Klingel-Dashboard
#    klingel_server.py, web/, config.ini, bin/ffmpeg, logs/, files/,
#    install.sh, uninstall.sh, ANLEITUNG.md, VERSION, paket/
#  Außerhalb des Ordners gibt es nur den Verweis
#    /etc/init.d/klingel-dashboard -> /root/Klingel-Dashboard/files/klingel-dashboard.init
#  (nötig für den Autostart).
#
#  Mehrfach ausführbar (Update). Eine vorhandene config.ini bleibt erhalten.
# ════════════════════════════════════════════════════════════════════

VERSION="4.2.3"
APP_DIR=${KLINGEL_APP_DIR:-/root/Klingel-Dashboard}
INIT=${KLINGEL_INIT:-/etc/init.d/klingel-dashboard}
OLD_DIR=/root/Klingel-Dashboard-Brume2          # Ordnername von v4.0.0
SRC_DIR=$(cd "$(dirname "$0")" && pwd)
PKG_DIR=${KLINGEL_PKG_DIR:-$SRC_DIR}
FFMPEG_URL_ARM64="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
FFMPEG_URL_AMD64="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
FFMPEG_URL_ARMHF="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-armhf-static.tar.xz"

# ── 0. Ordner zuerst anlegen – alles Weitere landet darin ────────────
[ "$(id -u)" = "0" ] || { echo "FEHLER: bitte als root ausführen"; exit 1; }
[ -f "$SRC_DIR/klingel_server.py" ] || { echo "FEHLER: klingel_server.py nicht neben install.sh gefunden"; exit 1; }
mkdir -p "$APP_DIR/web" "$APP_DIR/bin" "$APP_DIR/logs" "$APP_DIR/files" "$APP_DIR/paket" \
	|| { echo "FEHLER: Ordner $APP_DIR konnte nicht angelegt werden"; exit 1; }
LOG="$APP_DIR/logs/install.log"
echo "=== Installation v$VERSION am $(date) ===" > "$LOG"

say()  { echo ""; echo "==> $*"; echo "==> $*" >> "$LOG"; }
ok()   { echo "    OK: $*"; echo "    OK: $*" >> "$LOG"; }
warn() { echo "    WARNUNG: $*"; echo "    WARNUNG: $*" >> "$LOG"; }
die()  { echo ""; echo "FEHLER: $*"; echo "FEHLER: $*" >> "$LOG";
         echo "Details: $LOG"; exit 1; }

echo "════════════════════════════════════════════════"
echo "  Klingel-Dashboard Brume 2  v$VERSION – Installation"
echo "  Ordner: $APP_DIR"
echo "════════════════════════════════════════════════"

# Altinstallation v4.0.0 übernehmen (anderer Ordnername)
if [ "$OLD_DIR" != "$APP_DIR" ] && [ -d "$OLD_DIR" ]; then
	[ -x "$INIT" ] && "$INIT" stop >/dev/null 2>&1
	[ -f "$OLD_DIR/config.ini" ] && [ ! -f "$APP_DIR/config.ini" ] && cp "$OLD_DIR/config.ini" "$APP_DIR/"
	[ -x "$OLD_DIR/bin/ffmpeg" ] && [ ! -x "$APP_DIR/bin/ffmpeg" ] && mv "$OLD_DIR/bin/ffmpeg" "$APP_DIR/bin/"
	rm -rf "$OLD_DIR"
	[ -f /etc/sysupgrade.conf ] && sed -i "\#^$OLD_DIR/\$#d" /etc/sysupgrade.conf
	ok "alte Installation $OLD_DIR übernommen und entfernt"
fi

ARCH=$(uname -m)
case "$ARCH" in
	aarch64|arm64) FFMPEG_URL=$FFMPEG_URL_ARM64 ;;
	x86_64)        FFMPEG_URL=$FFMPEG_URL_AMD64 ;;
	armv7*)        FFMPEG_URL=$FFMPEG_URL_ARMHF ;;
	*)             FFMPEG_URL=""; warn "unbekannte Architektur $ARCH – ffmpeg bitte selbst bereitstellen" ;;
esac
ok "Architektur: $ARCH"

# ── 1. Programmdateien ───────────────────────────────────────────────
say "Programm nach $APP_DIR kopieren"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
	cp "$SRC_DIR/klingel_server.py" "$APP_DIR/" || die "Kopieren fehlgeschlagen"
	cp "$SRC_DIR/web/"*.html "$APP_DIR/web/"
	cp "$SRC_DIR/files/"* "$APP_DIR/files/"
	for f in ANLEITUNG.md VERSION install.sh uninstall.sh; do
		[ -f "$SRC_DIR/$f" ] && cp "$SRC_DIR/$f" "$APP_DIR/"
	done
fi
chmod +x "$APP_DIR/klingel_server.py" "$APP_DIR"/*.sh "$APP_DIR/files/klingel-dashboard.init" 2>/dev/null
if [ -f "$APP_DIR/config.ini" ]; then
	ok "vorhandene config.ini bleibt erhalten"
fi
# Installationspaket mit in den Ordner nehmen
if [ -n "$KLINGEL_PKG_FILE" ] && [ -f "$KLINGEL_PKG_FILE" ]; then
	case "$KLINGEL_PKG_FILE" in
		"$APP_DIR"/*) ;;
		*) mv "$KLINGEL_PKG_FILE" "$APP_DIR/paket/" && ok "Installationspaket nach $APP_DIR/paket/ verschoben" ;;
	esac
fi
ok "Dateien kopiert"

# ── 2. Python 3 ──────────────────────────────────────────────────────
OPKG_UPDATED=0
opkg_need() {   # opkg_need paket...
	if [ "$OPKG_UPDATED" = "0" ]; then
		echo "    opkg update ..."
		opkg update >>"$LOG" 2>&1 || warn "opkg update meldete Fehler (siehe $LOG)"
		OPKG_UPDATED=1
	fi
	opkg install "$@" >>"$LOG" 2>&1
}

say "Python 3 prüfen"
if python3 -c "import http.server, urllib.request, json, select, socketserver" 2>/dev/null; then
	ok "$(python3 --version 2>&1)"
else
	command -v opkg >/dev/null || die "python3 fehlt und opkg ist nicht vorhanden"
	echo "    installiere python3 (einige MB, dauert etwas) ..."
	opkg_need python3 || opkg_need python3-light python3-urllib python3-email python3-codecs python3-logging python3-openssl
	python3 -c "import http.server, urllib.request, json, select, socketserver" 2>/dev/null \
		|| die "python3 konnte nicht installiert werden"
	ok "$(python3 --version 2>&1)"
fi

DL=""
if command -v curl >/dev/null 2>&1; then DL="curl"; elif command -v wget >/dev/null 2>&1; then DL="wget"; fi

# ── 3. ffmpeg mit H.264 ──────────────────────────────────────────────
# Das ffmpeg aus den OpenWrt-Paketquellen ist ohne H.264-Decoder gebaut
# (Patent-Option abgeschaltet) und kann RTSP-Kameras daher NICHT umwandeln.
# Deshalb wird ein statisch gelinktes ffmpeg nach $APP_DIR/bin geladen.
has_h264() { "$1" -hide_banner -decoders 2>/dev/null | grep -qE '^ *V[^ ]* +h264 '; }

say "ffmpeg mit H.264-Decoder prüfen"
if [ -x "$APP_DIR/bin/ffmpeg" ] && has_h264 "$APP_DIR/bin/ffmpeg"; then
	ok "vorhanden: $("$APP_DIR/bin/ffmpeg" -version 2>/dev/null | head -n1)"
else
	TMPD="$APP_DIR/.ffmpeg-tmp"
	rm -rf "$TMPD"; mkdir -p "$TMPD"
	ARCHIVE=""
	# a) Archiv liegt im Ordner paket/ oder neben dem Installationspaket (Brume ohne Internet)
	for f in "$APP_DIR"/paket/ffmpeg-*static*.tar.xz "$SRC_DIR"/ffmpeg-*static*.tar.xz "$PKG_DIR"/ffmpeg-*static*.tar.xz; do
		[ -f "$f" ] && ARCHIVE="$f" && ok "nutze lokales Archiv $(basename "$f")" && break
	done
	# lokales Archiv mit in den Ordner nehmen
	case "$ARCHIVE" in
		""|"$APP_DIR"/*) ;;
		*) mv "$ARCHIVE" "$APP_DIR/paket/" && ARCHIVE="$APP_DIR/paket/$(basename "$ARCHIVE")" ;;
	esac
	# b) herunterladen
	if [ -z "$ARCHIVE" ] && [ -n "$FFMPEG_URL" ]; then
		echo "    lade statisches ffmpeg (ca. 25 MB) ..."
		echo "    $FFMPEG_URL"
		ARCHIVE="$TMPD/ffmpeg.tar.xz"
		if [ "$DL" = "curl" ]; then
			curl -fL --retry 3 --connect-timeout 20 -o "$ARCHIVE" "$FFMPEG_URL" 2>>"$LOG"
		elif [ "$DL" = "wget" ]; then
			wget -O "$ARCHIVE" "$FFMPEG_URL" 2>>"$LOG"
		fi
		if [ ! -s "$ARCHIVE" ]; then
			# Zertifikate fehlen? einmal nachinstallieren und erneut versuchen
			opkg_need ca-bundle ca-certificates curl
			curl -fL --retry 3 --connect-timeout 20 -o "$ARCHIVE" "$FFMPEG_URL" 2>>"$LOG"
		fi
		[ -s "$ARCHIVE" ] || ARCHIVE=""
	fi
	if [ -n "$ARCHIVE" ]; then
		echo "    entpacke ..."
		if ! tar -xJf "$ARCHIVE" -C "$TMPD" 2>>"$LOG"; then
			command -v xz >/dev/null 2>&1 || opkg_need xz-utils xz
			command -v xz >/dev/null 2>&1 && xz -dc "$ARCHIVE" | tar -x -C "$TMPD"
		fi
		BIN=$(find "$TMPD" -type f -name ffmpeg | head -n1)
		if [ -n "$BIN" ]; then
			mv "$BIN" "$APP_DIR/bin/ffmpeg" && chmod +x "$APP_DIR/bin/ffmpeg"
		fi
	fi
	rm -rf "$TMPD"
	if [ -x "$APP_DIR/bin/ffmpeg" ] && has_h264 "$APP_DIR/bin/ffmpeg"; then
		ok "installiert: $("$APP_DIR/bin/ffmpeg" -version 2>/dev/null | head -n1)"
	else
		rm -f "$APP_DIR/bin/ffmpeg"
		if command -v ffmpeg >/dev/null 2>&1 && has_h264 "$(command -v ffmpeg)"; then
			ok "System-ffmpeg mit H.264 gefunden: $(command -v ffmpeg)"
		else
			warn "kein ffmpeg mit H.264-Decoder installiert!"
			warn "Die Dashboards laufen, RTSP-Kamerabilder aber erst mit ffmpeg."
			warn "Lösung: ffmpeg-release-arm64-static.tar.xz von johnvansickle.com/ffmpeg"
			warn "nach $APP_DIR/paket/ kopieren und install.sh erneut starten."
		fi
	fi
fi

# ── 4. Autostart ─────────────────────────────────────────────────────
say "Autostart einrichten"
INIT_SRC="$APP_DIR/files/klingel-dashboard.init"
[ -f "$INIT_SRC" ] || die "Init-Skript fehlt"
sed -i "s#^APP_DIR=.*#APP_DIR=$APP_DIR#" "$INIT_SRC"
chmod +x "$INIT_SRC"
rm -f "$INIT"
ln -s "$INIT_SRC" "$INIT" || die "Verweis $INIT konnte nicht angelegt werden"
"$INIT" enable && ok "Autostart aktiv ($INIT -> $INIT_SRC)"

# Bei Firmware-Updates der Brume behalten
if [ -f /etc/sysupgrade.conf ]; then
	for p in "$APP_DIR/" "$INIT"; do
		grep -qxF "$p" /etc/sysupgrade.conf || echo "$p" >> /etc/sysupgrade.conf
	done
	ok "in /etc/sysupgrade.conf eingetragen"
fi

# ── 5. Start ─────────────────────────────────────────────────────────
say "Dienst starten"
"$INIT" stop >/dev/null 2>&1
sleep 1
"$INIT" start
sleep 4

PORTS=$(sed -n 's/^port *= *\([0-9]*\)/\1/p' "$APP_DIR/config.ini" 2>/dev/null | tail -n2 | tr '\n' ' ')
SETUP=$(sed -n 's/^einrichtung_port *= *\([0-9]*\)/\1/p' "$APP_DIR/config.ini" 2>/dev/null)
[ -n "$SETUP" ] || SETUP=8083
[ -n "$PORTS" ] || PORTS="8081 8082"

echo ""
echo "════════════════════════════════════════════════"
echo "  Klingel-Dashboard Brume 2 v$VERSION ist installiert"
echo "  Ordner: $APP_DIR"
echo "════════════════════════════════════════════════"
IPS=$(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -v '^127\.')
[ -n "$IPS" ] || IPS="<IP-der-Brume>"
for IP in $IPS; do
	for P in $PORTS; do echo "  Dashboard:    http://$IP:$P"; done
	echo "  Einrichtung:  http://$IP:$SETUP"
done
echo ""
echo "  Log:          $APP_DIR/logs/klingel.log"
echo "  Neustart:     $INIT restart"
echo "════════════════════════════════════════════════"
echo "=== fertig ===" >> "$LOG"
