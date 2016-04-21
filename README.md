#### Wpas

Simple tool for basic management of `wpa_supplicant` through dbus. Goal is to
be more friendly than `wpa_cli`.

#### Installation

```
pip install wpas
```

python gobject is required(`apt-get install python-gi` in ubuntu).

#### Scan networks

```
wpas scan
```

#### Connect to a network

```
wpas connect SSID [--save wifi.json]
```

the `--save` argument will store ssid/password(which is prompted by `connect`)
into `wifi.json`. If the file exists, it will be appended.

#### Load networks from wifi.json

```
wpas load wifi.json
```

This will add all networks/ssids saved to `wifi.json` in `wpa_supplicant`.

#### Specify wireless interface

`wpas` will try to determine your wireless interface name through the `ip link`
shell comand. If it fails or you have more than one wifi card, specify it with
the `--ifname` option(before subcommands). Example:

```
wpas --ifname=wlp1s5 scan
wpas --ifname=wlp1s5 connect SSID
```

#### Example with ubuntu

First, create a systemd service(`/etc/systemd/system/wpa-configure.service`) to load all saved networks during boot:

```systemd
[Unit]
Description=Configure wpa supplicant at startup
After=wpa_supplicant.service
ConditionPathExists=/usr/local/bin/wpas
ConditionPathExists=/etc/wifi.json

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wpas load /etc/wifi.json

[Install]
Also=wpa_supplicant.service
WantedBy=multi-user.target 
```

Add new networks with `sudo wpas connect SSID --save /etc/wifi.json` and they
will be loaded automatically at boot.

To use without root permissions, add your user to the `netdev` group.
