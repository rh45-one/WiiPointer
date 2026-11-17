# Development

## Code layout

| File | Responsibility |
| --- | --- |
| `wii_app.py` | GTK window, tray menu, dialogs, appearance, and preferences |
| `desktop_backend.py` | App-owned process, settings persistence, status stream, and command queue |
| `pointer_settings.py` | Shared defaults and validation for pointer settings and mappings |
| `wii_mouse.py` | Kernel device selection, sensor fusion, calibration, mapped outputs, and watch loop |
| `bluetooth_helper.py` | Asynchronous BlueZ calls and connection-state descriptions |
| `install-desktop.py` | Per-user launcher installation and legacy-service migration |
| `prototypes/` | Standalone browser design experiments; not the desktop app |

Run the native app directly during development:

```sh
/usr/bin/python3 wii_app.py
```

Use `/usr/bin/python3` on Debian/Ubuntu so the app can find the distribution's
PyGObject, Cairo, and evdev packages. There is no web frontend build step.

## Process and settings flow

`Gtk.Application` provides single-instance behavior over the user session bus.
The app starts `wii_mouse.py --watch --app-managed` as a child and owns its lifetime.
A shared `flock` prevents the desktop and CLI from reading the same remote twice.
Linux parent-death signaling and a private pipe's EOF stop the child if the app dies.
Normal quit sends SIGTERM, waits for input cleanup, and kills a stuck child after
five seconds.

The app sends newline-delimited JSON commands on the child's stdin. The backend
validates complete settings before applying them. Commands are coalesced by type
and written without blocking the GTK thread, including during calibration.
Settings and pause changes release held outputs and reset motion filtering.
Neither operation changes gyro bias or recreates virtual devices.

The child writes ordinary logs and `WIIPOINTER `-prefixed JSON status messages
to stdout. The app keeps the last 200 lines for Connection details. BlueZ requests
use asynchronous D-Bus calls so scanning and connection timeouts do not block GTK.

Gyro bias lives in memory for the app session. Disconnects and pause/resume keep it.
Initial calibration measures it once; HOME hold replaces it after a successful
measurement. Selecting a different address clears it. Bias is never reused from
a previous app session by the desktop app.

## Button handling

`MappedButtons` computes the union of outputs required by held physical buttons.
This prevents one button from releasing an output still needed by another button,
including shared Super modifiers. Mapping changes and disconnects release all
declared mouse buttons and keys. HOME tap uses its selected action; HOME hold
always runs calibration and cannot be remapped.

Only the actions listed in `pointer_settings.ACTIONS` are accepted. Mappings do not
execute shell commands or arbitrary programs. Validation keeps an aim action and
a left-click action available.

## Tests

See the README for commands. The native UI suite runs under Xvfb without a remote.
Its application ID is unique to the test process, so it cannot attach to a user's
running WiiPointer instance. UI preferences use a temporary config directory.
Lifecycle tests use isolated runtime locks and real subprocesses; they never enable
the systemd service.

The browser prototypes are archived but retain their model and Playwright tests.
Their fake sensor and connection states do not control the native backend.
