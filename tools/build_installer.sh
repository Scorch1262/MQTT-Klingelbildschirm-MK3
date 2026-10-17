#!/bin/sh
# Baut ein einzelnes, selbstentpackendes Installationsskript:
#   dist/klingel-dashboard-brume2_v<VERSION>.sh
# Auf der Brume:  sh klingel-dashboard-brume2_v<VERSION>.sh
set -e
cd "$(dirname "$0")/.."
VERSION=$(cat VERSION)
OUT=dist/klingel-dashboard-brume2_v$VERSION.sh
mkdir -p dist
TMP=$(mktemp -d)
mkdir -p "$TMP/Klingel-Dashboard"
cp -r klingel_server.py web files install.sh uninstall.sh ANLEITUNG.md VERSION "$TMP/Klingel-Dashboard/"
cat > "$OUT" <<EOF
#!/bin/sh
# Klingel-Dashboard Brume 2 v$VERSION – Installationspaket (selbstentpackend)
# Aufruf auf der Brume 2 als root:  sh $(basename "$OUT")
T=/tmp/klingel-install-\$\$
rm -rf "\$T"; mkdir -p "\$T" || exit 1
LINE=\$(awk '/^__ARCHIV_START__\$/ { print NR + 1; exit 0 }' "\$0")
tail -n +"\$LINE" "\$0" | tar -xzf - -C "\$T" || { echo "FEHLER: Paket beschaedigt"; exit 1; }
P=\$(cd "\$(dirname "\$0")" && pwd)/\$(basename "\$0")
KLINGEL_PKG_DIR=\$(dirname "\$P") KLINGEL_PKG_FILE="\$P" sh "\$T/Klingel-Dashboard/install.sh"
RC=\$?
rm -rf "\$T"
exit \$RC
__ARCHIV_START__
EOF
tar -czf - -C "$TMP" Klingel-Dashboard >> "$OUT"
chmod +x "$OUT"
rm -rf "$TMP"
echo "erstellt: $OUT ($(wc -c < "$OUT") Bytes)"
