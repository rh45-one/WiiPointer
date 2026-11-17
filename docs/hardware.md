# Hardware setup

## Requirements

Use a genuine Wii Remote with MotionPlus built in, or a compatible external
MotionPlus accessory. The kernel must expose the remote's buttons, gyroscope,
and accelerometer through `hid-wiimote`. BlueZ handles Bluetooth. The app uses
evdev to read sensors and uinput to create a relative mouse and keyboard, including
under GNOME Wayland.

WiiPointer does not use IR or a sensor bar. It measures rotation, so it cannot know
the absolute point on your screen that the remote faces. Hold your aim button to
move the cursor and release it to reposition your hand.

## Input permissions

Check that the kernel modules and device are available:

```sh
sudo modprobe uinput
sudo modprobe hid_wiimote
ls -l /dev/uinput
```

The logged-in desktop user needs read access to the remote's `/dev/input/event*`
interfaces and read/write access to `/dev/uinput`. The connection helper checks
whether uinput is writable; Connection details shows backend errors. A waiting
message can also mean the MotionPlus interfaces have not appeared yet.

For a local desktop session managed by systemd-logind, a narrowly scoped udev rule
can grant active-session access. Review it before installing it as
`/etc/udev/rules.d/70-wiipointer.rules`:

```udev
SUBSYSTEM=="misc", KERNEL=="uinput", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{id/vendor}=="057e", TAG+="uaccess"
```

Reload rules and reconnect the remote. Reboot if your distribution does not apply
the uinput ACL to the existing device:

```sh
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
```

The Nintendo rule covers Nintendo input devices, not every keyboard. uinput access
allows software running as your user to inject input into your session. Avoid
world-writable input devices and do not run the app as root. Adding your user to
the broad `input` group also exposes other input devices and is not the recommended
default.

## Bluetooth connection

The connection helper reads BlueZ state over the system D-Bus. It can turn an
adapter on, start discovery while the helper is open, and request a connection to
a paired remote. It stops its discovery request when the helper closes. Authorization
errors from BlueZ appear in the helper.

Pairing stays in GNOME Bluetooth settings, which provides the system's pairing
agent. Keep the remote awake during pairing. Some remote/BlueZ combinations need
the red SYNC button instead of 1 + 2; follow the distribution's Wii Remote pairing
instructions if GNOME asks for an unsupported PIN. WiiPointer does not guess PINs.

If Bluetooth says connected but the app keeps waiting:

1. Check input permissions and that `hid_wiimote` loaded.
2. Confirm MotionPlus is present and recognized.
3. Check that the helper's selected address matches the remote.
4. Quit other `wii-clicker` instances or the old service.

The app starts with the development remote's address until you choose yours in the
helper. A different remote starts a new calibration and disables roll compensation.
Your selection is stored in your local settings file.

## Roll compensation

`accelerometer.json` contains measured offsets and scales for the development
remote, identified in that file. Its X/Z calibration uses four opposing poses;
the longitudinal Y scale is estimated. These measurements are not a universal
Wii Remote calibration.

For a different remote, leave roll compensation off until you have measured its
stationary accelerometer offsets and scales. The file's `offset` and `scale`
arrays each contain three values in the kernel sensor's axis order. Scales must
be between 20 and 200; offsets must be within ±500. Restart the app after replacing
the file with your measurements. The app currently does not provide an accelerometer
calibration wizard or per-remote calibration files.

Roll compensation combines gyro rotation and gravity. Strong linear acceleration
can disturb the estimate. Aiming pauses near straight up/down because roll becomes
ambiguous. HOME calibration corrects gyro bias, not absolute heading or accelerometer
offsets.

## Calibration lights

During settling, the four player LEDs count down. During measurement, one LED
chases back and forth. Their previous state returns after calibration, including
on failure. A light pattern ending does not by itself confirm success; check the
app status.

LED animation is optional. Without LED access, input and calibration still work.
The included `99-wii-clicker-leds.rules` is a development-machine example: it names
a specific Bluetooth address and user. Replace both before using it on another
machine, then install the edited rule:

```sh
sudo install -m 0644 99-wii-clicker-leds.rules /etc/udev/rules.d/99-wii-clicker-leds.rules
sudo udevadm control --reload-rules
```

Reconnect the remote after installing the rule. It grants access only to the four
LED brightness files; it does not grant input permissions or start a daemon.

## Hardware checks still needed

Automated tests use simulated sensor data, mocked BlueZ responses, and disconnected
processes. Test these with the actual laptop and remote:

- Pair, wake, disconnect, and reconnect the remote.
- Complete the initial calibration and reject a moving measurement.
- Change pointer settings while aiming; confirm there is no calibration cycle.
- Try each mapping, dragging, overlapping shortcuts, pause/resume, and HOME hold.
- Check LED restoration, logout, suspend/resume, and a low battery.
