# IBKR Client Portal Gateway (bundled)

This folder is Interactive Brokers' own **Client Portal Gateway** (downloaded from IBKR:
http://download2.interactivebrokers.com/portal/clientportal.gw.zip), copied unchanged except for `root/conf.yaml`:

* `listenPort: 5757` - a port private to this app (macOS uses 5000 for AirPlay).
* `ips.allow` is only `127.0.0.1`, so nothing but this computer can reach it.

FinSi starts it with the app (`source/collector/ibkr_gateway.py`) and stops it when the app quits. It needs Java 8 (update 192) or newer
on the Mac. You sign in to IBKR in the browser at https://localhost:5757; your IBKR password never reaches FinSi.
IBKR's software stays subject to IBKR's own terms.
