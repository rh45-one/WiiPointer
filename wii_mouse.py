#!/usr/bin/python3
"""MotionPlus relative mouse and presentation buttons through Linux uinput."""

import argparse
import ctypes
from collections import deque
from contextlib import ExitStack
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import select
import signal
import statistics
import struct
import sys
import time

from evdev import InputDevice, UInput, ecodes as e, list_devices
from pointer_settings import DEFAULT_MAPPINGS, validate

AXES = (e.ABS_RX, e.ABS_RY, e.ABS_RZ)
UNITS_PER_DPS = 8192 * 9 / 440
SLIDES = {e.KEY_RIGHT: e.KEY_PAGEDOWN, e.KEY_LEFT: e.KEY_PAGEUP,
          e.KEY_UP: e.KEY_PAGEUP, e.KEY_DOWN: e.KEY_PAGEDOWN}
VOLUME = {e.KEY_NEXT: e.KEY_VOLUMEUP, e.KEY_PREVIOUS: e.KEY_VOLUMEDOWN}
REMOTE_MAC = '2c:10:c1:df:a8:54'
HOME_THRESHOLD = 0.45  # seconds: below = show desktop, at/above = calibrate


def report(state, message):
    print('WIIPOINTER ' + json.dumps({'state': state, 'message': message}), flush=True)


class RemoteUnavailable(RuntimeError):
    pass


class CalibrationError(RuntimeError):
    pass


def hid_parent(device):
    return Path('/sys/class/input', Path(device.path).name, 'device').resolve().parent.parent


def is_our_remote(device, remote_mac=REMOTE_MAC):
    properties = dict(line.split('=', 1) for line in
                      (hid_parent(device)/'uevent').read_text().splitlines() if '=' in line)
    return properties.get('HID_UNIQ', '').lower() == remote_mac.lower()


def devices(stack, roll_compensation=True, remote_mac=REMOTE_MAC):
    found = {"Nintendo Wii Remote": [], "Nintendo Wii Remote Motion Plus": []}
    if roll_compensation:
        found['Nintendo Wii Remote Accelerometer'] = []
    for path in list_devices():
        try:
            device = InputDevice(path)
        except (PermissionError, FileNotFoundError):
            continue
        if device.name in found and device.info.vendor == 0x057E:
            try:
                ours = is_our_remote(device, remote_mac)
            except FileNotFoundError:
                ours = False
            if not ours:
                device.close()
                continue
            stack.callback(device.close)
            found[device.name].append(device)
        else:
            device.close()
    if any(len(matches) != 1 for matches in found.values()):
        raise RemoteUnavailable("Waiting for the configured Wii Remote and accessible sensor interfaces.")
    selected = [matches[0] for matches in found.values()]
    parents = [Path('/sys/class/input', Path(d.path).name, 'device').resolve().parent
               for d in selected]
    if len(set(parents)) != 1:
        raise RuntimeError("Buttons and sensors belong to different HID devices.")
    for device in selected:
        # EVIOCSCLOCKID is not exposed by Debian's python-evdev binding.
        fcntl.ioctl(device.fd, 0x400445A0, struct.pack('i', time.CLOCK_MONOTONIC))
    return selected[0], selected[1], selected[2] if roll_compensation else None


class AxisInput:
    def __init__(self, device):
        self.device = device
        self.state = self.snapshot()
        self.syncing = False

    def snapshot(self):
        return [self.device.absinfo(axis).value for axis in AXES]

    def feed(self, event):
        if event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
            self.syncing = True
            return 'dropped'
        if self.syncing:
            if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                self.state = self.snapshot()
                self.syncing = False
            return None
        if event.type == e.EV_ABS and event.code in AXES:
            self.state[AXES.index(event.code)] = event.value
        if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
            return 'frame'
        return None


def calibration_result(rows):
    if len(rows) < 200:
        raise CalibrationError("Too few gyro samples; check connection and retry.")
    bias = [statistics.mean(column) for column in zip(*rows)]
    noise = [statistics.pstdev(column) for column in zip(*rows)]
    if max(noise) > 80 or max(map(abs, bias)) > 1500:
        raise CalibrationError("Calibration rejected: remote moved or readings were abnormal.")
    return bias, noise


class CalibrationLights:
    """Settling countdown, then measurement chase; restore original lights."""

    def __init__(self, paths, settling=0):
        self.paths = paths
        self.settling = settling
        self.saved = []
        self.current = []
        self.started = time.monotonic()

    def __enter__(self):
        try:
            if len(self.paths) != 4:
                raise OSError('Four player LEDs were not found')
            for path in self.paths:
                if '[none]' not in path.with_name('trigger').read_text():
                    raise OSError('Player LEDs have an active kernel trigger')
            # Some driver versions report 255 despite max_brightness being 1.
            self.saved = [int(int(path.read_text()) > 0) for path in self.paths]
            self.current = list(self.saved)
            self.tick(self.started)
        except (OSError, ValueError) as exc:
            self.restore()
            self.saved = []
            print(f'Calibration lights unavailable: {exc}. Calibration still works.', flush=True)
        return self

    def restart_settling(self, now):
        self.started = now
        self.tick(now)

    def tick(self, now):
        if not self.saved:
            return
        elapsed = max(0, now-self.started)
        if elapsed < self.settling:
            remaining = math.ceil(4*(1-elapsed/self.settling))
            values = [int(i < remaining) for i in range(4)]
        else:
            active = (0, 1, 2, 3, 2, 1)[int((elapsed-self.settling)/.1) % 6]
            values = [int(i == active) for i in range(4)]
        try:
            for i, (path, value) in enumerate(zip(self.paths, values)):
                if value != self.current[i]:
                    path.write_text(str(value)+'\n')
                    self.current[i] = value
        except OSError as exc:
            self.restore()
            self.saved = []
            print(f'Calibration lights stopped: {exc}. Calibration continues.', flush=True)

    def restore(self):
        for path, value in zip(self.paths, self.saved):
            try:
                path.write_text(str(value)+'\n')
            except OSError:
                pass  # Device may have disconnected, or LED permission was denied.

    def __exit__(self, *_):
        self.restore()


def calibrate(gyro, settling=1):
    hid = hid_parent(gyro.device)
    paths = [hid/'leds'/f'{hid.name}:blue:p{i}'/'brightness' for i in range(4)]
    with CalibrationLights(paths, settling) as lights:
        return measure_bias(gyro, lights, settling)


def measure_bias(gyro, lights, settling=1):
    report('calibrating', 'Keep the remote on a stable surface. Measuring a still five-second window.')
    print(f"Calibrating: {settling}s settling delay, then a stable 5s measurement (30s maximum). Keep the remote still.", flush=True)
    now = time.monotonic()
    lights.restart_settling(now)
    warmup = now + settling
    deadline = now + 30
    samples = deque()
    next_check = warmup + 5
    waiting_reported = False
    while time.monotonic() < deadline:
        lights.tick(time.monotonic())
        ready, _, _ = select.select([gyro.device], [], [], max(0, min(.1, deadline-time.monotonic())))
        if not ready:
            continue
        for event in gyro.device.read():
            result = gyro.feed(event)
            if result == 'dropped':
                samples.clear()
                now = time.monotonic()
                lights.restart_settling(now)
                warmup = now + settling
                next_check = warmup + 5
            elif (result == 'frame' and time.monotonic() >= warmup
                  and event.timestamp() >= warmup):
                stamp = event.timestamp()
                samples.append((stamp, tuple(gyro.state)))
                # Retain a contiguous five-second window, including its boundary frame.
                while len(samples) > 1 and samples[1][0] <= stamp-5:
                    samples.popleft()
                if stamp < next_check or samples[0][0] > stamp-5:
                    continue
                next_check = stamp + .25
                try:
                    bias, noise = calibration_result([row for _, row in samples])
                except CalibrationError:
                    if not waiting_reported:
                        print('Waiting for a stable five-second window; keep the remote still.', flush=True)
                        waiting_reported = True
                    continue
                print(f"Calibration OK ({len(samples)} frames): bias={bias}, noise={noise}", flush=True)
                return bias
    if samples:
        rows = [row for _, row in samples]
        noise = [round(statistics.pstdev(column), 2) for column in zip(*rows)]
        print(f'Rejected calibration diagnostics: frames={len(rows)}, axis noise={noise}', flush=True)
        for name, column in zip(('RX', 'RY', 'RZ'), zip(*rows)):
            median = statistics.median(column)
            unusual = sum(abs(v-median) > 100 for v in column)
            print(f'{name}: median={median}, min={min(column)}, max={max(column)}, '
                  f'samples >100 from median={unusual}', flush=True)
    raise CalibrationError('Calibration timed out: no stable five-second window received within 30s.')


class Orientation:
    """Gravity vector in accelerometer coordinates, predicted using the gyro."""

    def __init__(self, calibration):
        self.offset = calibration['offset']
        self.scale = calibration['scale']
        for values in (self.offset, self.scale):
            if len(values) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError('Invalid accelerometer calibration')
        if any(not 20 <= v <= 200 for v in self.scale) or any(abs(v)>500 for v in self.offset):
            raise ValueError('Invalid accelerometer offset or scale')
        self.gravity = None

    def reset(self):
        self.gravity = None

    def update(self, state, bias, acceleration, dt):
        if self.gravity is not None and 0 < dt <= .05:
            # Gyro order is yaw/roll/pitch; accel axes are pitch/roll/yaw.
            omega = [(state[i]-bias[i])/UNITS_PER_DPS*math.pi/180 for i in (2, 1, 0)]
            speed = math.hypot(*omega)
            if speed > 0:
                axis = [v/speed for v in omega]
                x, y, z = axis
                gx, gy, gz = self.gravity
                cross = (y*gz-z*gy, z*gx-x*gz, x*gy-y*gx)
                dot = sum(a*b for a, b in zip(axis, self.gravity))
                angle = -speed*dt
                c, s = math.cos(angle), math.sin(angle)
                self.gravity = [v*c+k*s+a*dot*(1-c)
                                for v, k, a in zip(self.gravity, cross, axis)]
        if acceleration is not None:
            measured = [(v-o)/s for v, o, s in zip(acceleration, self.offset, self.scale)]
            norm = math.hypot(*measured)
            # Reject obvious linear acceleration, rather than interpreting it as tilt.
            if .85 <= norm <= 1.15:
                measured = [v/norm for v in measured]
                if self.gravity is None:
                    self.gravity = measured
                else:
                    correction = -math.expm1(-max(0, dt)/.5)
                    fused = [g+correction*(m-g) for g, m in zip(self.gravity, measured)]
                    length = math.hypot(*fused)
                    if length > 1e-6:
                        self.gravity = [v/length for v in fused]
        if self.gravity is None or math.hypot(self.gravity[0], self.gravity[2]) < .25:
            return None
        return math.atan2(self.gravity[0], self.gravity[2])


class Motion:
    def __init__(self, sensitivity, smoothing, deadzone, invert_x, invert_y, acceleration=0):
        self.sensitivity = sensitivity
        self.smoothing = smoothing
        self.deadzone = deadzone
        self.acceleration = acceleration
        self.signs = (-1 if invert_x else 1, -1 if invert_y else 1)
        self.reset()

    def reset(self):
        self.filtered = [0., 0.]
        self.remainder = [0., 0.]

    def gain(self, speed):
        fraction = min(1., max(0., (speed-5)/55))
        curve = fraction*fraction*(3-2*fraction)
        return 1 + self.acceleration*(2*curve-.5)

    def step(self, state, bias, dt, roll=0):
        alpha = 1 if self.smoothing == 0 else -math.expm1(-dt/self.smoothing)
        yaw = (state[0]-bias[0])/UNITS_PER_DPS
        pitch = (state[2]-bias[2])/UNITS_PER_DPS
        c, s = math.cos(roll), math.sin(roll)
        rates = (c*yaw+s*pitch, c*pitch-s*yaw)
        for i, rate in enumerate(rates):
            # Soft deadzone avoids a discontinuity at the noise threshold.
            rate = math.copysign(max(0, abs(rate)-self.deadzone), rate)
            self.filtered[i] += alpha*(rate-self.filtered[i])
        # One gain for both axes preserves direction, including diagonals.
        gain = self.gain(math.hypot(*self.filtered))
        result = []
        for i in range(2):
            self.remainder[i] += self.filtered[i]*gain*self.sensitivity*dt*self.signs[i]
            whole = math.trunc(self.remainder[i])
            self.remainder[i] -= whole
            result.append(whole)
        return result


BUTTON_NAMES = {e.BTN_SOUTH: 'A', e.BTN_EAST: 'B', e.KEY_UP: 'Up', e.KEY_DOWN: 'Down',
                e.KEY_LEFT: 'Left', e.KEY_RIGHT: 'Right', e.KEY_NEXT: '+', e.KEY_PREVIOUS: '-',
                e.BTN_MODE: 'HOME', e.BTN_1: '1', e.BTN_2: '2'}
MOUSE_KEYS = [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE]
KEYBOARD_KEYS = [e.KEY_PAGEUP, e.KEY_PAGEDOWN, e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN,
                 e.KEY_LEFTMETA, e.KEY_A, e.KEY_D]
ACTION_KEYS = {'left_click': [(True, e.BTN_LEFT)], 'right_click': [(True, e.BTN_RIGHT)],
               'middle_click': [(True, e.BTN_MIDDLE)], 'page_up': [(False, e.KEY_PAGEUP)],
               'page_down': [(False, e.KEY_PAGEDOWN)], 'volume_up': [(False, e.KEY_VOLUMEUP)],
               'volume_down': [(False, e.KEY_VOLUMEDOWN)], 'desktop': [(False, e.KEY_LEFTMETA), (False, e.KEY_D)],
               'overview': [(False, e.KEY_LEFTMETA)], 'quick_settings': [(False, e.KEY_LEFTMETA), (False, e.KEY_A)],
               'none': [], 'aim': []}


class MappedButtons:
    def __init__(self, mouse, keyboard, mappings):
        self.mouse, self.keyboard, self.mappings = mouse, keyboard, mappings
        self.held, self.active = set(), set()

    def sync(self, target):
        for is_mouse, code in sorted(self.active-target, key=lambda key: key[1] == e.KEY_LEFTMETA):
            (self.mouse if is_mouse else self.keyboard).write(e.EV_KEY, code, 0)
        for is_mouse, code in sorted(target-self.active, key=lambda key: key[1] != e.KEY_LEFTMETA):
            (self.mouse if is_mouse else self.keyboard).write(e.EV_KEY, code, 1)
        self.mouse.syn()
        self.keyboard.syn()
        self.active = target

    def event(self, code, value):
        name = BUTTON_NAMES.get(code)
        if name is None:
            return
        if value:
            self.held.add(name)
        else:
            self.held.discard(name)
        self.sync({key for button in self.held for key in ACTION_KEYS[self.mappings[button]]})

    def tap_home(self):
        previous = self.active.copy()
        self.sync(previous | set(ACTION_KEYS[self.mappings['HOME']]))
        self.sync(previous)

    def aiming(self):
        return any(self.mappings[name] == 'aim' for name in self.held)

    def release(self):
        for output, keys in ((self.mouse, MOUSE_KEYS), (self.keyboard, KEYBOARD_KEYS)):
            for key in keys:
                output.write(e.EV_KEY, key, 0)
            output.syn()
        self.active.clear()
        self.held.clear()


class AppControl:
    """Nonblocking, newline-delimited commands on the private parent pipe."""
    def __init__(self, stream):
        self.fd = stream.fileno()
        os.set_blocking(self.fd, False)
        self.buffer = ''
        self.version = 0

    def poll(self, args):
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        if not data:
            raise KeyboardInterrupt
        self.buffer += data.decode('utf-8')
        if len(self.buffer) > 131072:
            raise ValueError('App command exceeds size limit')
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            try:
                event = json.loads(line)
                if event['type'] == 'settings':
                    settings = validate(event['settings'])
                    if getattr(args, 'remote_mac', settings['remote_mac']).lower() != settings['remote_mac'].lower():
                        args.session_bias = None
                        args.remote_changed = True
                    for key, value in settings.items():
                        if key != 'theme':
                            setattr(args, key, value)
                    self.version += 1
                    report('settings', 'Pointer settings and button mappings applied without recalibration.')
                elif event['type'] == 'pause' and type(event['paused']) is bool:
                    args.paused = event['paused']
                    self.version += 1
            except (ValueError, KeyError, TypeError) as exc:
                print(f'App command rejected: {exc}', flush=True)


def poll_control(args):
    control = getattr(args, 'control', None)
    if control:
        control.poll(args)
    return control.version if control else 0


def run(buttons, gyro, accel, bias, args, stack):
    orientation = Orientation(json.loads(args.accel_calibration.read_text())) if accel and args.roll_compensation else None
    mouse = stack.enter_context(UInput({e.EV_KEY: MOUSE_KEYS,
        e.EV_REL: [e.REL_X, e.REL_Y]}, name="Wii Air Mouse"))
    keyboard = stack.enter_context(UInput({e.EV_KEY: KEYBOARD_KEYS}, name="Wii Presentation Clicker"))
    buttons.grab()
    stack.callback(buttons.ungrab)
    motion = Motion(args.sensitivity, args.smoothing, args.deadzone,
                    args.invert_x, args.invert_y, args.acceleration)
    mapped = MappedButtons(mouse, keyboard, getattr(args, 'mappings', DEFAULT_MAPPINGS))
    version = getattr(getattr(args, 'control', None), 'version', 0)
    syncing = False
    last_frame = 0
    last_tick = time.monotonic()
    home_pressed_at = None
    end = last_tick + args.seconds if args.seconds else math.inf
    inputs = [buttons, gyro.device] + ([accel.device] if accel else [])

    def release():
        mapped.release()
        motion.reset()

    print("Ready: B=hold to aim, A=click, D-pad Up/Down=page, +/-=volume. "
          "HOME press=desktop, hold=calibrate. 1=app view, 2=quick settings.", flush=True)
    print(f"Automatic stop in {args.seconds}s." if args.seconds else "Ctrl+C to stop.", flush=True)
    report('ready', 'Connected and calibrated. Your button mappings are active.')
    try:
        while time.monotonic() < end:
            updated = poll_control(args)
            if getattr(args, 'remote_changed', False):
                args.remote_changed = False
                raise RemoteUnavailable('Switching to the selected remote.')
            if updated != version:
                release()
                mapped.mappings = args.mappings
                motion = Motion(args.sensitivity, args.smoothing, args.deadzone,
                                args.invert_x, args.invert_y, args.acceleration)
                if accel and args.roll_compensation and orientation is None:
                    orientation = Orientation(json.loads(args.accel_calibration.read_text()))
                elif orientation:
                    orientation.reset()
                version = updated
                home_pressed_at = None
            ready, _, _ = select.select(inputs, [], [], .01)
            recalibrate = False
            home_tap = False
            for device in ready:
                for event in device.read():
                    if accel and device is accel.device:
                        if accel.feed(event) == 'dropped':
                            orientation.reset()
                            motion.reset()
                        continue
                    if device is gyro.device:
                        result = gyro.feed(event)
                        if result == 'dropped':
                            last_frame = 0
                            release()
                            home_pressed_at = None
                            if orientation:
                                orientation.reset()
                        elif result == 'frame':
                            last_frame = event.timestamp()
                        continue
                    if event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
                        release()
                        home_pressed_at = None
                        syncing = True
                        continue
                    if syncing:
                        if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                            syncing = False
                        continue
                    if event.type != e.EV_KEY or event.value not in (0, 1):
                        continue
                    if event.code == e.BTN_MODE:
                        if event.value:
                            home_pressed_at = time.monotonic()
                        else:
                            if home_pressed_at is not None and time.monotonic()-home_pressed_at < HOME_THRESHOLD:
                                home_tap = True
                            elif home_pressed_at is not None:
                                recalibrate = True
                            home_pressed_at = None
                    elif not getattr(args, 'paused', False):
                        mapped.event(event.code, event.value)
            if home_tap:
                if not getattr(args, 'paused', False):
                    mapped.tap_home()
            if home_pressed_at is not None and time.monotonic()-home_pressed_at >= HOME_THRESHOLD:
                recalibrate = True
                home_pressed_at = None
            if recalibrate:
                release()
                try:
                    bias = calibrate(gyro, settling=5)
                    args.session_bias = bias
                except CalibrationError as exc:
                    print(f"{exc} Previous calibration retained.", flush=True)
                    report('ready', f'{exc} Previous calibration retained.')
                else:
                    report('ready', 'Calibration complete. Your button mappings are active.')
                last_frame = 0
                last_tick = time.monotonic()
                if orientation:
                    orientation.reset()
                continue
            now = time.monotonic()
            dt = now-last_tick
            last_tick = now
            if not 0 <= now-last_frame < .1 or dt > .05:
                motion.reset()
                if orientation:
                    orientation.reset()
                continue
            roll = orientation.update(gyro.state, bias, None if accel.syncing else accel.state, dt) if orientation and args.roll_compensation else 0
            if getattr(args, 'paused', False) or not mapped.aiming() or roll is None:
                motion.reset()
                continue
            x, y = motion.step(gyro.state, bias, dt, roll)
            if x or y:
                mouse.write(e.EV_REL, e.REL_X, x)
                mouse.write(e.EV_REL, e.REL_Y, y)
                mouse.syn()
    finally:
        release()


def run_session(args):
    poll_control(args)
    args.remote_changed = False
    if getattr(args, 'paused', False):
        raise RemoteUnavailable('Input is paused. Resume it from the app or tray.')
    with ExitStack() as stack:
        buttons, device, accel_device = devices(stack,
            True if getattr(args, 'app_managed', False) else args.roll_compensation,
            getattr(args, 'remote_mac', REMOTE_MAC))
        gyro = AxisInput(device)
        if args.bias_file:
            saved = json.loads(args.bias_file.read_text())
            bias = saved['bias']
            if (not 0 <= time.time()-saved['time'] <= 300 or len(bias) != 3
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v)>1500 for v in bias)):
                raise RuntimeError('Invalid or expired calibration; recalibrate on the table.')
        elif getattr(args, 'session_bias', None) is not None:
            bias = list(args.session_bias)
        else:
            bias = calibrate(gyro, settling=5 if args.watch else 1)
            args.session_bias = list(bias)
        if args.calibrate_only:
            args.calibrate_only.write_text(json.dumps({'time': time.time(), 'bias': bias})+'\n')
        else:
            accel = AxisInput(accel_device) if accel_device else None
            run(buttons, gyro, accel, bias, args, stack)


def watch(args):
    print(f'Watching for Wii Remote {REMOTE_MAC}. Press A to reconnect, then set it down.', flush=True)
    waiting = False
    while True:
        try:
            return run_session(args)
        except RemoteUnavailable as exc:
            if not waiting:
                print(exc, flush=True)
                report('waiting', str(exc))
            waiting = True
        except CalibrationError as exc:
            print(f'{exc} Set the remote down; calibration will retry.', flush=True)
            report('calibrating', f'{exc} Set the remote down; retrying shortly.')
            waiting = False
        except OSError as exc:
            if exc.errno not in (errno.ENODEV, errno.ENXIO, errno.EIO):
                raise
            print('Remote disconnected; released virtual input. Waiting for reconnection.', flush=True)
            report('waiting', 'Remote disconnected. Press A to reconnect, then set it down.')
            waiting = True
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sensitivity', type=float, default=12, help='pixels per degree')
    parser.add_argument('--smoothing', type=float, default=.025, help='filter time constant in seconds')
    parser.add_argument('--deadzone', type=float, default=.3, help='degrees per second')
    parser.add_argument('--acceleration', type=float, default=.3,
                        help='speed-based gain strength, 0=linear, 0.3=gentle (range 0..1)')
    parser.add_argument('--invert-x', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--invert-y', action='store_true')
    parser.add_argument('--seconds', type=float, default=0, help='stop after this many seconds; 0=unlimited')
    parser.add_argument('--calibrate-only', type=Path, help='save calibration and exit')
    parser.add_argument('--bias-file', type=Path, help='use a calibration saved within the last five minutes')
    parser.add_argument('--roll-compensation', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--accel-calibration', type=Path,
                        default=Path(__file__).with_name('accelerometer.json'))
    parser.add_argument('--watch', action='store_true',
                        help='wait for this remote and recover after disconnects; calibrate each connection')
    parser.add_argument('--app-managed', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--app-parent', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--remote-mac', default=REMOTE_MAC, help='Bluetooth address of your Wii Remote')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', args.remote_mac):
        parser.error('invalid Bluetooth address')
    args.paused = False
    args.mappings = DEFAULT_MAPPINGS.copy()
    args.session_bias = None
    if args.watch and (args.bias_file or args.calibrate_only or args.seconds):
        parser.error('--watch cannot be combined with --bias-file, --calibrate-only, or --seconds')
    if not math.isfinite(args.acceleration) or not 0 <= args.acceleration <= 1:
        parser.error('acceleration must be finite and between 0 and 1')
    for name in ('sensitivity', 'smoothing', 'deadzone', 'seconds'):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (name == 'sensitivity' and value == 0):
            parser.error(f'{name} must be finite and nonnegative (sensitivity must be positive)')
    with ExitStack() as stack:
        if args.app_managed:
            # Release virtual input even if the desktop process crashes.
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), 'Could not bind backend lifetime to the app')
            if os.getppid() == 1 or (args.app_parent is not None and os.getppid() != args.app_parent):
                raise SystemExit('The desktop app has already exited.')
            runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
            lock = stack.enter_context((runtime/'wii-clicker.lock').open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit('Another WiiPointer backend is running. Stop wii-clicker before retrying.')
            args.control = AppControl(sys.stdin)
        if args.watch:
            watch(args)
        else:
            run_session(args)


def stop(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop)
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped.')
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Wii mouse stopped: {exc}')
