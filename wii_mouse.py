#!/usr/bin/python3
"""MotionPlus relative mouse and presentation buttons through Linux uinput."""

import argparse
from collections import deque
from contextlib import ExitStack
import errno
import fcntl
import json
import math
from pathlib import Path
import select
import signal
import statistics
import struct
import time

from evdev import InputDevice, UInput, ecodes as e, list_devices

AXES = (e.ABS_RX, e.ABS_RY, e.ABS_RZ)
UNITS_PER_DPS = 8192 * 9 / 440
SLIDES = {e.KEY_RIGHT: e.KEY_PAGEDOWN, e.KEY_LEFT: e.KEY_PAGEUP}
VOLUME = {e.KEY_NEXT: e.KEY_VOLUMEUP, e.KEY_PREVIOUS: e.KEY_VOLUMEDOWN}
REMOTE_MAC = '2c:10:c1:df:a8:54'
HOME_THRESHOLD = 0.45  # seconds: below = show desktop, at/above = calibrate


class RemoteUnavailable(RuntimeError):
    pass


class CalibrationError(RuntimeError):
    pass


def hid_parent(device):
    return Path('/sys/class/input', Path(device.path).name, 'device').resolve().parent.parent


def is_our_remote(device):
    properties = dict(line.split('=', 1) for line in
                      (hid_parent(device)/'uevent').read_text().splitlines() if '=' in line)
    return properties.get('HID_UNIQ', '').lower() == REMOTE_MAC


def devices(stack, roll_compensation=True):
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
                ours = is_our_remote(device)
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


def run(buttons, gyro, accel, bias, args, stack):
    orientation = Orientation(json.loads(args.accel_calibration.read_text())) if accel else None
    mouse = stack.enter_context(UInput({e.EV_KEY: [e.BTN_LEFT],
        e.EV_REL: [e.REL_X, e.REL_Y]}, name="Wii Air Mouse"))
    keyboard = stack.enter_context(UInput({e.EV_KEY: list(SLIDES.values()) + list(VOLUME.values())
        + [e.KEY_LEFTMETA, e.KEY_A]}, name="Wii Presentation Clicker"))
    buttons.grab()
    stack.callback(buttons.ungrab)
    motion = Motion(args.sensitivity, args.smoothing, args.deadzone,
                    args.invert_x, args.invert_y, args.acceleration)
    held = set()
    syncing = False
    last_frame = 0
    last_tick = time.monotonic()
    home_pressed_at = None
    end = last_tick + args.seconds if args.seconds else math.inf
    inputs = [buttons, gyro.device] + ([accel.device] if accel else [])

    def release():
        mouse.write(e.EV_KEY, e.BTN_LEFT, 0)
        mouse.syn()
        for key in SLIDES.values():
            keyboard.write(e.EV_KEY, key, 0)
        for key in VOLUME.values():
            keyboard.write(e.EV_KEY, key, 0)
        keyboard.write(e.EV_KEY, e.KEY_A, 0)
        keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, 0)
        keyboard.syn()
        held.clear()
        motion.reset()

    print("Ready: B=hold to aim, A=click, D-pad Up/Down=page, +/-=volume. "
          "HOME press=desktop, hold=calibrate. 1=app view, 2=quick settings.", flush=True)
    print(f"Automatic stop in {args.seconds}s." if args.seconds else "Ctrl+C to stop.", flush=True)
    try:
        while time.monotonic() < end:
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
                    if event.value:
                        held.add(event.code)
                    else:
                        held.discard(event.code)
                    if event.code == e.BTN_SOUTH:
                        mouse.write(e.EV_KEY, e.BTN_LEFT, event.value)
                        mouse.syn()
                    elif event.code in SLIDES:
                        keyboard.write(e.EV_KEY, SLIDES[event.code], event.value)
                        keyboard.syn()
                    elif event.code in VOLUME:
                        keyboard.write(e.EV_KEY, VOLUME[event.code], event.value)
                        keyboard.syn()
                    elif event.code == e.BTN_MODE:
                        if event.value:
                            home_pressed_at = time.monotonic()
                        else:
                            if home_pressed_at is not None and time.monotonic()-home_pressed_at < HOME_THRESHOLD:
                                home_tap = True
                            home_pressed_at = None
                    elif event.code == e.BTN_1:
                        keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, event.value)
                        keyboard.syn()
                    elif event.code == e.BTN_2:
                        if event.value:
                            keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, 1)
                            keyboard.write(e.EV_KEY, e.KEY_A, 1)
                            keyboard.syn()
                        else:
                            keyboard.write(e.EV_KEY, e.KEY_A, 0)
                            keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, 0)
                            keyboard.syn()
                    elif event.code == e.BTN_EAST and not event.value:
                        motion.reset()
            if home_tap:
                release()
                keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, 1)
                keyboard.write(e.EV_KEY, e.KEY_D, 1)
                keyboard.syn()
                keyboard.write(e.EV_KEY, e.KEY_D, 0)
                keyboard.write(e.EV_KEY, e.KEY_LEFTMETA, 0)
                keyboard.syn()
                motion.reset()
                last_frame = 0
                last_tick = time.monotonic()
                continue
            if recalibrate:
                release()
                try:
                    bias = calibrate(gyro, settling=5)
                except CalibrationError as exc:
                    print(f"{exc} Previous calibration retained.", flush=True)
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
            roll = orientation.update(gyro.state, bias, None if accel.syncing else accel.state, dt) if orientation else 0
            if e.BTN_EAST not in held or roll is None:
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
    with ExitStack() as stack:
        buttons, device, accel_device = devices(stack, args.roll_compensation)
        gyro = AxisInput(device)
        if args.bias_file:
            saved = json.loads(args.bias_file.read_text())
            bias = saved['bias']
            if (not 0 <= time.time()-saved['time'] <= 300 or len(bias) != 3
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v)>1500 for v in bias)):
                raise RuntimeError('Invalid or expired calibration; recalibrate on the table.')
        else:
            bias = calibrate(gyro, settling=5 if args.watch else 1)
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
            waiting = True
        except CalibrationError as exc:
            print(f'{exc} Set the remote down; calibration will retry.', flush=True)
            waiting = False
        except OSError as exc:
            if exc.errno not in (errno.ENODEV, errno.ENXIO, errno.EIO):
                raise
            print('Remote disconnected; released virtual input. Waiting for reconnection.', flush=True)
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
    args = parser.parse_args()
    if args.watch and (args.bias_file or args.calibrate_only or args.seconds):
        parser.error('--watch cannot be combined with --bias-file, --calibrate-only, or --seconds')
    if not math.isfinite(args.acceleration) or not 0 <= args.acceleration <= 1:
        parser.error('acceleration must be finite and between 0 and 1')
    for name in ('sensitivity', 'smoothing', 'deadzone', 'seconds'):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (name == 'sensitivity' and value == 0):
            parser.error(f'{name} must be finite and nonnegative (sensitivity must be positive)')
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
