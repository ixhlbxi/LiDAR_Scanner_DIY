# First-boot smoke checklist (run on the Pi after `sudo deploy/install.sh`)

Each line is pass/fail. Record the outcome and date in the audit report row named.

1. `git -C /opt/rover status` is not needed: the units import from `/opt/rover/src`.
   `python3 -c "import sys; sys.path.insert(0,'/opt/rover/src'); import rover; print(rover.__version__)"`
   → prints the version. (sanity)
2. `sudo systemctl start rover-telemetry && sleep 5 && systemctl is-active rover-telemetry`
   → `active`. Then `journalctl -u rover-telemetry -n 20` shows `Watchdog started` or
   `Watchdog disabled by config` and NO `start operation timed out`. (T1-002)
3. `cat /run/rover/status.json` → JSON with `schema_version`. (RuntimeDirectory, T2-003)
4. `ls /var/lib/rover/data/` → one session directory. (StateDirectory, T2-001)
5. `sudo systemctl stop rover-telemetry` returns within 10 s and the session has
   `metadata.json`. (T1-029)
6. `sudo systemctl start rover` with the stepper connected → journal shows no
   `lgpio` / `LG_WD` error and the motor steps. (PrivateTmp, T2-002)
7. With the camera enabled: journal shows `Captured images/img_000000.jpg`, no
   `TypeError`. (T1-005)
8. With the F9P connected and pyubx2 installed: `status.json` shows a plausible
   `lat`/`lon` (not 0.0) within 60 s of a sky view. (T1-006)
9. Pull the LD19 USB cable mid-session → journal shows one WARNING
   `lidar: 5 consecutive read failures — subsystem disabled`, the service stays
   `active`, telemetry keeps publishing. (T1-003)
10. `python3 -c "import RPi.GPIO as g; print(g.__file__)"` → path contains
    `rpi_lgpio` or `lgpio`, not `RPi/GPIO`. If it does not, `sudo apt remove
    python3-rpi.gpio && pip install rpi-lgpio`. (T1-033; stage 4 adds a code guard)
11. `sudo deploy/install.sh` a second time → prints `kept /etc/rover/config.toml`.
