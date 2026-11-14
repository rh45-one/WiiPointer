import unittest
import math
import json
import errno
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from evdev import InputEvent, ecodes as e

from wii_mouse import CalibrationLights, Motion, Orientation, UNITS_PER_DPS, calibration_result, measure_bias
from wii_mouse import CalibrationError, RemoteUnavailable, is_our_remote, run, run_session, watch


class MotionTests(unittest.TestCase):
    def test_roll_compensation_restores_direction(self):
        for roll in (0, math.pi/2, -math.pi/2, math.pi, .7):
            c, s = math.cos(roll), math.sin(roll)
            # Same world-relative yaw=30, pitch=40 at each body roll.
            state = [(c*30-s*40)*UNITS_PER_DPS, 0,
                     (s*30+c*40)*UNITS_PER_DPS]
            motion = Motion(10, 0, 0, True, False)
            x, y = motion.step(state, [0, 0, 0], 1, roll)
            self.assertAlmostEqual(x, -300, delta=1)
            self.assertAlmostEqual(y, 400, delta=1)

    def test_acceleration_is_gentle_bounded_and_monotonic(self):
        motion = Motion(12, .025, .3, False, False, .3)
        self.assertAlmostEqual(motion.gain(0), .85)
        self.assertAlmostEqual(motion.gain(5), .85)
        self.assertAlmostEqual(motion.gain(60), 1.45)
        gains = [motion.gain(speed) for speed in range(301)]
        self.assertEqual(gains, sorted(gains))
        self.assertTrue(all(.85 <= gain <= 1.45 for gain in gains))

    def test_acceleration_can_be_disabled(self):
        motion = Motion(12, .025, .3, False, False, 0)
        for speed in (0, 5, 20, 90, 1000):
            self.assertEqual(motion.gain(speed), 1)

    def test_acceleration_survives_roll_compensation(self):
        for speed in (2, 30, 120):
            expected = Motion(12, .025, .3, True, False, .3)
            expected_total = [0, 0]
            for _ in range(100):
                delta = expected.step([speed*UNITS_PER_DPS, 0, 0], [0]*3, .01)
                expected_total = [a+b for a, b in zip(expected_total, delta)]
            for roll in (math.pi/2, -math.pi/2, math.pi):
                motion = Motion(12, .025, .3, True, False, .3)
                state = [math.cos(roll)*speed*UNITS_PER_DPS, 0,
                         math.sin(roll)*speed*UNITS_PER_DPS]
                total = [0, 0]
                for _ in range(100):
                    delta = motion.step(state, [0]*3, .01, roll)
                    total = [a+b for a, b in zip(total, delta)]
                for actual, baseline in zip(total, expected_total):
                    self.assertAlmostEqual(actual, baseline, delta=1)
            linear = Motion(12, .025, .3, True, False, 0)
            linear_total = sum(linear.step([speed*UNITS_PER_DPS, 0, 0], [0]*3, .01)[0]
                               for _ in range(100))
            self.assertNotEqual(expected_total[0], linear_total)

    def test_acceleration_preserves_diagonal_direction(self):
        motion = Motion(100, 0, 0, False, False, .3)
        x, y = motion.step([30*UNITS_PER_DPS, 0, 40*UNITS_PER_DPS], [0, 0, 0], 1)
        self.assertAlmostEqual(x/y, .75, places=3)

    def test_bias_produces_no_motion(self):
        motion = Motion(12, .025, .3, False, False)
        for _ in range(100):
            self.assertEqual(motion.step([-329, 308, -458], [-329, 308, -458], .01), [0, 0])

    def test_axes_scale_and_fractional_accumulation(self):
        motion = Motion(1, 0, 0, False, True)
        total = [0, 0]
        for _ in range(100):
            delta = motion.step([10*UNITS_PER_DPS, 9999, 20*UNITS_PER_DPS], [0, 0, 0], .01)
            total = [a+b for a, b in zip(total, delta)]
        self.assertAlmostEqual(total[0], 10, delta=1)
        self.assertAlmostEqual(total[1], -20, delta=1)

    def test_reset_clears_smoothing_and_remainder(self):
        motion = Motion(12, .025, .3, False, False)
        motion.step([10000, 0, 10000], [0, 0, 0], .01)
        motion.reset()
        self.assertEqual(motion.step([0, 0, 0], [0, 0, 0], .01), [0, 0])

    def test_stationary_calibration(self):
        bias, noise = calibration_result([(-329, 308, -458)]*300)
        self.assertEqual(bias, [-329, 308, -458])
        self.assertEqual(noise, [0, 0, 0])

    def test_rejects_movement_and_short_capture(self):
        for rows in ([(0, 0, 0)]*10, [(0, 0, 0), (1000, 0, 0)]*200):
            with self.assertRaises(RuntimeError):
                calibration_result(rows)


class CalibrationTimingTests(unittest.TestCase):
    def simulate(self, moving_until):
        clock = [0.]
        device = Mock()
        gyro = SimpleNamespace(device=device, state=[0, 0, 0])

        def ready(*_):
            clock[0] += .01
            return [device], [], []

        def read():
            sec = int(clock[0])
            return [InputEvent(sec, int((clock[0]-sec)*1e6), e.EV_SYN, e.SYN_REPORT, 0)]

        def feed(event):
            gyro.state = [0, (3000 if int(clock[0]*100) % 2 else -3000)
                          if clock[0] < moving_until else 300, 0]
            return 'frame'

        device.read.side_effect = read
        gyro.feed = feed
        with patch('wii_mouse.time.monotonic', side_effect=lambda: clock[0]), \
             patch('wii_mouse.select.select', side_effect=ready):
            result = measure_bias(gyro, Mock(), settling=5)
        return result, clock[0]

    def test_home_ignores_wobble_during_five_second_delay(self):
        bias, elapsed = self.simulate(moving_until=5)
        self.assertEqual(bias, [0, 300, 0])
        self.assertGreaterEqual(elapsed, 10)

    def test_motion_during_measurement_is_still_rejected(self):
        with self.assertRaises(RuntimeError):
            self.simulate(moving_until=math.inf)

    def test_waits_for_settling_after_countdown(self):
        bias, elapsed = self.simulate(moving_until=7)
        self.assertEqual(bias, [0, 300, 0])
        self.assertGreaterEqual(elapsed, 12)
        self.assertLess(elapsed, 13)


class CalibrationLightsTests(unittest.TestCase):
    def led_files(self, root):
        paths = []
        for i in range(4):
            directory = root/str(i)
            directory.mkdir()
            path = directory/'brightness'
            path.write_text('255\n' if i == 0 else '0\n')
            (directory/'trigger').write_text('[none] timer\n')
            paths.append(path)
        return paths

    def test_chase_and_restore_on_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.led_files(Path(directory))
            with self.assertRaises(RuntimeError):
                with CalibrationLights(paths) as lights:
                    lights.tick(lights.started+.16)
                    self.assertEqual([int(p.read_text()) for p in paths], [0, 1, 0, 0])
                    lights.tick(lights.started+.31)
                    self.assertEqual([int(p.read_text()) for p in paths], [0, 0, 0, 1])
                    raise RuntimeError('Calibration rejected')
            self.assertEqual([int(p.read_text()) for p in paths], [1, 0, 0, 0])

    def test_countdown_then_fast_measurement_chase(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.led_files(Path(directory))
            with CalibrationLights(paths, settling=5) as lights:
                for elapsed, expected in (
                    (0, [1, 1, 1, 1]),
                    (1.26, [1, 1, 1, 0]),
                    (2.51, [1, 1, 0, 0]),
                    (3.76, [1, 0, 0, 0]),
                    (5.01, [1, 0, 0, 0]),
                    (5.11, [0, 1, 0, 0]),
                    (5.31, [0, 0, 0, 1]),
                ):
                    lights.tick(lights.started+elapsed)
                    self.assertEqual([int(int(p.read_text()) > 0) for p in paths], expected)
                lights.restart_settling(lights.started+6)
                self.assertEqual([int(p.read_text()) for p in paths], [1, 1, 1, 1])
            self.assertEqual([int(p.read_text()) for p in paths], [1, 0, 0, 0])

    def test_countdown_uses_startup_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.led_files(Path(directory))
            with CalibrationLights(paths, settling=1) as lights:
                lights.tick(lights.started+.51)
                self.assertEqual([int(int(p.read_text()) > 0) for p in paths], [1, 1, 0, 0])
                lights.tick(lights.started+1.11)
                self.assertEqual([int(p.read_text()) for p in paths], [0, 1, 0, 0])

    def test_permission_failure_does_not_abort_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.led_files(Path(directory))
            with patch.object(Path, 'write_text', side_effect=PermissionError('LED access denied')):
                with CalibrationLights(paths) as lights:
                    lights.tick(lights.started+.2)
                    self.assertFalse(lights.saved)

    def test_missing_leds_are_optional(self):
        with CalibrationLights([]) as lights:
            self.assertFalse(lights.saved)


class RecoveryTests(unittest.TestCase):
    def test_only_the_configured_remote_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with patch('wii_mouse.hid_parent', return_value=parent):
                (parent/'uevent').write_text('HID_UNIQ=2C:10:C1:DF:A8:54\n')
                self.assertTrue(is_our_remote(Mock()))
                (parent/'uevent').write_text('HID_UNIQ=00:11:22:33:44:55\n')
                self.assertFalse(is_our_remote(Mock()))

    def test_waits_and_recovers_from_disconnect_and_failed_calibration(self):
        with patch('wii_mouse.run_session', side_effect=[
            RemoteUnavailable('Waiting'), OSError(errno.ENODEV, 'Disconnected'),
            CalibrationError('Still moving'), None,
        ]) as session, patch('wii_mouse.time.sleep') as sleep:
            watch(Mock())
        self.assertEqual(session.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_unexpected_permission_error_is_not_silently_retried(self):
        with patch('wii_mouse.run_session', side_effect=PermissionError(errno.EACCES, 'Denied')), \
             patch('wii_mouse.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                watch(Mock())
        sleep.assert_not_called()

    def test_reconnected_session_always_calibrates_with_settling_delay(self):
        args = SimpleNamespace(roll_compensation=True, watch=True,
                               bias_file=None, calibrate_only=None)
        buttons, device, gyro = Mock(), Mock(), Mock()
        with patch('wii_mouse.devices', return_value=(buttons, device, None)), \
             patch('wii_mouse.AxisInput', return_value=gyro), \
             patch('wii_mouse.calibrate', return_value=[1, 2, 3]) as calibrate, \
             patch('wii_mouse.run') as active:
            run_session(args)
        calibrate.assert_called_once_with(gyro, settling=5)
        self.assertEqual(active.call_args.args[3], [1, 2, 3])

    def test_disconnect_and_interrupt_release_outputs_and_grab(self):
        for error in (OSError(errno.ENODEV, 'Disconnected'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                buttons = Mock()
                buttons.read.side_effect = error
                gyro = SimpleNamespace(device=Mock())
                outputs = [MagicMock(), MagicMock()]
                for output in outputs:
                    output.__enter__.return_value = output
                args = SimpleNamespace(sensitivity=12, smoothing=.025, deadzone=.3,
                                       invert_x=True, invert_y=False, acceleration=.3, seconds=0)
                with patch('wii_mouse.UInput', side_effect=outputs), \
                     patch('wii_mouse.select.select', return_value=([buttons], [], [])):
                    with self.assertRaises(type(error)):
                        with ExitStack() as stack:
                            run(buttons, gyro, None, [0]*3, args, stack)
                outputs[0].write.assert_any_call(e.EV_KEY, e.BTN_LEFT, 0)
                for key in (e.KEY_PAGEUP, e.KEY_PAGEDOWN, e.KEY_VOLUMEUP,
                            e.KEY_VOLUMEDOWN, e.KEY_A, e.KEY_LEFTMETA):
                    outputs[1].write.assert_any_call(e.EV_KEY, key, 0)
                for output in outputs:
                    output.__exit__.assert_called_once()
                buttons.ungrab.assert_called_once()


class OrientationTests(unittest.TestCase):
    calibration = {'offset': [0, 0, 0], 'scale': [100, 100, 100]}

    def test_measured_poses(self):
        calibration = json.loads(Path(__file__).with_name('accelerometer.json').read_text())
        expected = {'face_up': 0, 'face_down': math.pi,
                    'buttons_left': -math.pi/2, 'buttons_right': math.pi/2}
        for name, angle in expected.items():
            orientation = Orientation(calibration)
            roll = orientation.update([0]*3, [0]*3, calibration['poses'][name], .01)
            difference = math.atan2(math.sin(roll-angle), math.cos(roll-angle))
            self.assertAlmostEqual(difference, 0, delta=.06)

    def test_gyro_predicts_roll_without_accel(self):
        orientation = Orientation(self.calibration)
        orientation.update([0]*3, [0]*3, [0, 0, 100], .01)
        for _ in range(100):
            roll = orientation.update([0, 90*UNITS_PER_DPS, 0], [0]*3, None, .01)
        self.assertAlmostEqual(roll, -math.pi/2)
        self.assertAlmostEqual(math.hypot(*orientation.gravity), 1)

    def test_rejects_large_acceleration(self):
        orientation = Orientation(self.calibration)
        orientation.update([0]*3, [0]*3, [0, 0, 100], .01)
        roll = orientation.update([0]*3, [0]*3, [200, 0, 100], .01)
        self.assertEqual(roll, 0)

    def test_near_vertical_pauses_and_reset_discards_estimate(self):
        orientation = Orientation(self.calibration)
        self.assertIsNone(orientation.update([0]*3, [0]*3, [0, 100, 0], .01))
        orientation.reset()
        self.assertIsNone(orientation.gravity)

    def test_invalid_calibration_rejected(self):
        with self.assertRaises(ValueError):
            Orientation({'offset': [0]*3, 'scale': [0]*3})


if __name__ == '__main__':
    unittest.main()
