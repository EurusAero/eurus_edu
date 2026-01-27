```bash
sudo nano /etc/init.d/network_setup
```

```bash
#!/bin/bash
### BEGIN INIT INFO
# Provides: network_setup
# Required-Start: $remote_fs $syslog
# Required-Stop: $remote_fs $syslog
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Short-Description:
# Description:
### END INIT INFO
NETPLAN_FILE="/etc/netplan/orangepi-default.yaml"

SSID_PREFIX="EURUS_EDU"

RAND_DIGITS=$(printf "%04d" $((RANDOM % 10000)))
SSID_NAME="${SSID_PREFIX}_${RAND_DIGITS}"

for i in {1..10}; do
    WIFI_IFACE=$(ls /sys/class/net | grep -E '^wl|^wlan' | head -n 1)
    ETH_IFACE=$(ls /sys/class/net | grep -E '^e|^en' | head -n 1)
    if [ -n "$WIFI_IFACE" ]; then
        break
    fi
    sleep 3
done

if [ -n "$WIFI_IFACE" ]; then
    cat <<EOF > "$NETPLAN_FILE"
network:
  version: 2
  renderer: NetworkManager
EOF

    # Блок Ethernet (если есть)
    if [ -n "$ETH_IFACE" ]; then
    cat <<EOF >> "$NETPLAN_FILE"
  ethernets:
    $ETH_IFACE:
      dhcp4: true
      optional: true
EOF
    fi

    cat <<EOF >> "$NETPLAN_FILE"
  wifis:
    $WIFI_IFACE:
      dhcp4: true
      optional: true
      access-points:
        "$SSID_NAME":
          auth:
            key-management: psk
            password: "euruswifi"
          mode: ap
          band: 5GHz
          networkmanager:
            passthrough:
              wifi-security.proto: "rsn"
EOF

    chmod 600 "$NETPLAN_FILE"
    netplan apply
fi

update-rc.d -f network_setup remove
rm -- "$0"
```

```bash
sudo chmod +x /etc/init.d/network_setup
sudo chown root:root /etc/init.d/network_setup
sudo update-rc.d network_setup defaults 95
```

Чтоб проверить создавшийся симлинк можно ввести:

```bash
ls -l /etc/rc*.d/*network*
```

Если нужно для кловера, то внутри конфига `/etc/init.d/network_setup` можно поменять это:

```bash
SSID_PREFIX="EURUS_EDU"
```

на это:

```bash
SSID_PREFIX="EURUS_CLOVER"
```
