from contextlib import ExitStack
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock, patch

from evdev import InputEvent, ecodes as e
from pointer_settings import default_settings, validate
from wii_mouse import AppControl, MappedButtons, ACTION_KEYS, run, run_session


class LiveControlTests(unittest.TestCase):
    def setUp(self):
        reader, self.writer = os.pipe()
        self.stream = os.fdopen(reader, 'rb')
        self.control = AppControl(self.stream)
        self.args = SimpleNamespace(**default_settings(), session_bias=[1, 2, 3], paused=False)

    def tearDown(self):
        self.stream.close()
        if self.writer is not None:
            os.close(self.writer)

    def send(self, event):
        os.write(self.writer, (json.dumps(event)+'\n').encode())
        self.control.poll(self.args)

    def test_all_pointer_settings_and_mappings_apply_without_changing_bias(self):
        settings = default_settings()
        settings.update(sensitivity=21, smoothing=.04, acceleration=.8, deadzone=.7,
                        invert_x=False, invert_y=True, roll_compensation=False)
        settings['mappings']['A'], settings['mappings']['B'] = 'aim', 'left_click'
        self.send({'type': 'settings', 'settings': settings})
        for key in settings:
            if key != 'theme':
                self.assertEqual(getattr(self.args, key), settings[key])
        self.assertEqual(self.args.session_bias, [1, 2, 3])
        self.assertEqual(self.control.version, 1)

    def test_pause_and_resume_preserve_bias(self):
        for paused in (True, False):
            self.send({'type': 'pause', 'paused': paused})
            self.assertEqual(self.args.paused, paused)
            self.assertEqual(self.args.session_bias, [1, 2, 3])

    def test_invalid_command_does_not_partially_apply(self):
        settings = default_settings()
        settings['sensitivity'] = 1000
        self.send({'type': 'settings', 'settings': settings})
        self.assertEqual(self.args.sensitivity, 12)
        self.assertEqual(self.control.version, 0)
        self.send({'type': 'pause', 'paused': 'yes'})
        self.assertFalse(self.args.paused)

    def test_new_remote_requires_its_own_initial_calibration(self):
        settings = default_settings()
        settings['remote_mac'] = '00:11:22:33:44:55'
        self.send({'type': 'settings', 'settings': settings})
        self.assertIsNone(self.args.session_bias)
        self.assertTrue(self.args.remote_changed)

    def test_partial_command_and_parent_pipe_closure(self):
        os.write(self.writer, b'{"type":"pause",')
        self.control.poll(self.args)
        self.assertFalse(self.args.paused)
        os.write(self.writer, b'"paused":true}\n')
        self.control.poll(self.args)
        self.assertTrue(self.args.paused)
        os.close(self.writer)
        self.writer = None
        with self.assertRaises(KeyboardInterrupt):
            self.control.poll(self.args)

    def test_reconnect_reuses_initial_bias(self):
        args = SimpleNamespace(roll_compensation=False, watch=True, bias_file=None,
                               calibrate_only=None)
        with patch('wii_mouse.devices', return_value=(Mock(), Mock(), None)), \
             patch('wii_mouse.AxisInput'), patch('wii_mouse.run') as active, \
             patch('wii_mouse.calibrate', return_value=[10, 20, 30]) as calibrate:
            run_session(args)
            run_session(args)
        calibrate.assert_called_once()
        self.assertEqual(active.call_count, 2)
        self.assertEqual(active.call_args.args[3], [10, 20, 30])

    def test_running_session_applies_settings_and_pause_without_calibration_or_new_devices(self):
        args = SimpleNamespace(**default_settings(), seconds=0, paused=False)
        clock, polls = [0.], [0]
        control = SimpleNamespace(version=0)
        def poll(_args):
            polls[0] += 1
            if polls[0] == 2:
                args.sensitivity = 24
                args.roll_compensation = False
                control.version += 1
            elif polls[0] == 3:
                args.paused = True
                control.version += 1
            elif polls[0] == 4:
                args.paused = False
                control.version += 1
            elif polls[0] == 5:
                raise KeyboardInterrupt
        control.poll = poll
        args.control = control
        buttons = Mock()
        buttons.read.return_value = [InputEvent(0, 0, e.EV_KEY, e.BTN_SOUTH, 1)]
        gyro = SimpleNamespace(device=Mock(), state=[0, 0, 0])
        outputs = [MagicMock(), MagicMock()]
        for output in outputs:
            output.__enter__.return_value = output
        def select(*_):
            clock[0] += .01
            return [buttons], [], []
        with patch('wii_mouse.UInput', side_effect=outputs) as devices, \
             patch('wii_mouse.select.select', side_effect=select), \
             patch('wii_mouse.time.monotonic', side_effect=lambda: clock[0]), \
             patch('wii_mouse.calibrate') as calibrate:
            with self.assertRaises(KeyboardInterrupt), ExitStack() as stack:
                run(buttons, gyro, None, [1, 2, 3], args, stack)
        calibrate.assert_not_called()
        self.assertEqual(devices.call_count, 2)
        outputs[0].write.assert_any_call(e.EV_KEY, e.BTN_LEFT, 0)
        self.assertEqual(args.sensitivity, 24)


class MappingTests(unittest.TestCase):
    def mapped(self):
        return MappedButtons(Mock(), Mock(), default_settings()['mappings'])

    def test_every_action_presses_and_releases_its_outputs(self):
        for action, keys in ACTION_KEYS.items():
            with self.subTest(action=action):
                mapped = self.mapped()
                mapped.mappings['1'] = action
                mapped.event(e.BTN_1, 1)
                self.assertEqual(mapped.active, set(keys))
                mapped.event(e.BTN_1, 0)
                self.assertFalse(mapped.active)

    def test_swapping_aim_and_click_is_supported(self):
        mapped = self.mapped()
        mapped.mappings['A'], mapped.mappings['B'] = 'aim', 'left_click'
        mapped.event(e.BTN_SOUTH, 1)
        self.assertTrue(mapped.aiming())
        mapped.event(e.BTN_EAST, 1)
        mapped.mouse.write.assert_called_with(e.EV_KEY, e.BTN_LEFT, 1)
        mapped.release()
        self.assertFalse(mapped.aiming())
        self.assertFalse(mapped.active)

    def test_overlapping_buttons_do_not_release_a_still_held_action(self):
        mapped = self.mapped()
        mapped.event(e.KEY_RIGHT, 1)
        mapped.event(e.KEY_DOWN, 1)
        mapped.event(e.KEY_RIGHT, 0)
        self.assertEqual(mapped.active, {(False, e.KEY_PAGEDOWN)})
        mapped.event(e.KEY_DOWN, 0)
        self.assertFalse(mapped.active)
        mapped.event(e.BTN_1, 1)
        mapped.event(e.BTN_2, 1)
        mapped.event(e.BTN_2, 0)
        self.assertEqual(mapped.active, {(False, e.KEY_LEFTMETA)})

    def test_home_tap_respects_mapping_and_preserves_other_held_keys(self):
        mapped = self.mapped()
        mapped.event(e.BTN_1, 1)
        mapped.tap_home()
        self.assertEqual(mapped.active, {(False, e.KEY_LEFTMETA)})
        mapped.keyboard.write.assert_any_call(e.EV_KEY, e.KEY_D, 1)
        mapped.keyboard.write.assert_any_call(e.EV_KEY, e.KEY_D, 0)

    def test_invalid_mappings_cannot_remove_required_controls(self):
        for key, action in (('B', 'none'), ('A', 'right_click'), ('HOME', 'aim'), ('1', 'shell_command')):
            settings = default_settings()
            settings['mappings'][key] = action
            with self.subTest(key=key, action=action), self.assertRaises(ValueError):
                validate(settings)
