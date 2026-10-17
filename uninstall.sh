#!/bin/sh
# Klingel-Dashboard Brume 2 – Deinstallation
APP_DIR=/root/Klingel-Dashboard-Brume2
INIT=/etc/init.d/klingel-dashboard

[ -x "$INIT" ] && "$INIT" stop && "$INIT" disable
rm -f "$INIT"
if command -v uci >/dev/null 2>&1 && uci -q get firewall.klingel_dashboard >/dev/null; then
	uci delete firewall.klingel_dashboard && uci commit firewall && /etc/init.d/firewall reload >/dev/null 2>&1
fi
[ -f /etc/sysupgrade.conf ] && sed -i "\#^$APP_DIR/\$#d; \#^$INIT\$#d" /etc/sysupgrade.conf
echo "Dienst entfernt. Programmordner $APP_DIR (mit config.ini) bleibt erhalten."
echo "Ganz löschen: rm -rf $APP_DIR"
