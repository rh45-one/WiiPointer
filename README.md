# WiiPointer

Wii Remote MotionPlus air mouse and presentation clicker for Linux, including
GNOME Wayland. Uses the kernel Wii driver, Python evdev and uinput; no IR bar.

The project lives in `/home/hugo/WiiPointer`. The existing `wii-clicker` command
and service name are retained for compatibility.

## Start and stop

1. Keep the Wii console off. Press **A** to reconnect the paired remote.
2. Set the remote on a stable table.
3. Run `wii-clicker` in a terminal. Leave it still during calibration (about six seconds).
4. Pick it up when calibration finishes. **Ctrl+C** stops the daemon and releases input.

When the automatic service below is enabled, you do not need the terminal command:
press A to reconnect, set the remote down, and wait for the calibration lights.

The command is a symlink in `~/.local/bin` pointing into this directory.
Don't run it with sudo. A runtime lock prevents duplicate launcher instances;
exit code 75 means another launcher instance owns the lock. Direct invocation of
`wii_mouse.py` bypasses this lock.

## Controls

| Button | Action |
| --- | --- |
| B (hold) | Gyro aiming; release stops immediately |
| A | Left mouse button, including dragging |
| D-pad Right / Left | Page Down / Page Up for slides |
| HOME | Five-second settling delay, then wait for a stable five-second bias measurement |

During settling, the player lights count down from four to one in four equal stages
(five seconds for HOME, one second at startup). During measurement,
one light chases back and forth at 100 ms per step. The lights return to their previous
state afterward, including on rejection or interruption.
The measurement uses a rolling five-second window, retaining the same movement
checks. If the remote wobbles, the chase continues until a stable window is found;
calibration fails after 30 seconds total rather than accepting noisy readings.
If calibration fails, HOME retains the previous bias; startup instead exits.
The light pattern ending alone doesn't distinguish success from failure: check the terminal.

## Options

```sh
wii-clicker --no-roll-compensation
wii-clicker --acceleration 0
wii-clicker --sensitivity 10 --smoothing 0.035
wii-clicker --help
```

Defaults: sensitivity 12 pixels/nominal degree, smoothing 25 ms, soft deadzone
0.3 nominal degrees/second, gentle speed-based acceleration, horizontal inversion,
and roll compensation. The default acceleration gain ranges from 0.85 to 1.45,
transitioning smoothly between 5 and 60 nominal degrees/second. GNOME may also
apply pointer acceleration. Options currently require restarting the daemon.

The accelerometer calibration in `accelerometer.json` was measured for
`2C:10:C1:DF:A8:54`; do not assume it fits another remote. X/Z offsets and scales
use four opposing poses; the longitudinal Y scale is estimated. Gravity and gyro
tracking compensate for roll; the accelerometer does not drive the cursor.
Strong linear acceleration can still disturb the estimate. Aiming pauses near
straight up/down, where roll is ambiguous. HOME corrects gyro bias, not absolute heading.

## Persistent LED access (one-time administrator setup)

The included udev rule grants user `hugo` access only to the four LED brightness
files of this specific Bluetooth remote. It does not grant general input or
uinput permissions, run the mouse as root, or enable automatic startup.

```sh
sudo install -m 0644 /home/hugo/WiiPointer/99-wii-clicker-leds.rules /etc/udev/rules.d/99-wii-clicker-leds.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=leds --sysname-match='0005:057E:0306.*:blue:p[0-3]'
sudo udevadm settle
```

The rule reads the HID parent's kernel properties directly, without depending on
the parent event having populated the udev database before the LEDs appear.
Without LED access the daemon still works, but logs a warning and skips the animation.

## Automatic launch and recovery

The user service starts with the GNOME graphical session and stops on logout.
It waits for Bluetooth remote `2C:10:C1:DF:A8:54`, identified through the kernel's
HID properties rather than unstable event numbers. No root daemon is used.

```sh
systemctl --user enable /home/hugo/WiiPointer/wii-clicker.service
# Set the remote down before starting:
systemctl --user start wii-clicker
```

Each connection gets a fresh gyro calibration with a five-second settling countdown.
If calibration fails, it retries after two seconds; keep the remote stationary.
On disconnect, mouse buttons and slide keys are released, virtual devices are removed,
and the process waits for the remote again. It checks for available input devices
every two seconds while waiting. Unexpected process failures are restarted by systemd.
It does not re-pair devices or wake a powered-off remote: press A to reconnect.

```sh
systemctl --user status wii-clicker --no-pager
journalctl --user -u wii-clicker -n 40 --no-pager
systemctl --user stop wii-clicker
systemctl --user restart wii-clicker
# Disable automatic launch and stop it:
systemctl --user disable --now wii-clicker
```

While the service is running it owns the launcher lock, even when disconnected.
Stop it before running `wii-clicker` manually. For now, change service options using
`systemctl --user edit wii-clicker`, then restart with the remote on the table:

```ini
[Service]
ExecStart=
ExecStart=%h/.local/bin/wii-clicker --watch --no-roll-compensation
```

`wii-clicker --watch` also provides connection recovery without installing the service;
Ctrl+C stops that foreground watcher. Watch mode does not accept cached bias files,
calibration-only mode, or a timed run. Manual mode without `--watch` still exits on
disconnect. A reboot/login and suspend/resume should be tested on the actual laptop.

## Tests

```sh
cd /home/hugo/WiiPointer
/usr/bin/python3 -m unittest -v test_wii_mouse
```
