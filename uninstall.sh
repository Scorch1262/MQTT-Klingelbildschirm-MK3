#!/bin/sh
# Klingel-Dashboard Brume 2 – Deinstallation
#   sh uninstall.sh          -> Dienst entfernen, Ordner bleibt (mit config.ini)
#   sh uninstall.sh --alles  -> zusätzlich den ganzen Ordner löschen
APP_DIR=$(cd "$(dirname "$0")" && pwd)
INIT=/etc/init.d/klingel-dashboard

[ -e "$INIT" ] && "$INIT" stop && "$INIT" disable
rm -f "$INIT"
if command -v uci >/dev/null 2>&1 && uci -q get firewall.klingel_dashboard >/dev/null; then
	uci delete firewall.klingel_dashboard && uci commit firewall && /etc/init.d/firewall reload >/dev/null 2>&1
fi
[ -f /etc/sysupgrade.conf ] && sed -i "\#^$APP_DIR/\$#d; \#^$INIT\$#d" /etc/sysupgrade.conf

if [ "$1" = "--alles" ]; then
	rm -rf "$APP_DIR"
	echo "Klingel-Dashboard vollständig entfernt."
else
	echo "Dienst entfernt. Der Ordner $APP_DIR (mit config.ini) bleibt erhalten."
	echo "Ganz löschen: sh $APP_DIR/uninstall.sh --alles"
fi
