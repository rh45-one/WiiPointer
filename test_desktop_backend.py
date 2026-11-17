import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from desktop_backend import Backend, DEFAULTS, RANGES, command, load_settings, save_settings, validate


class PreferencesTests(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config/settings.json'
            self.assertEqual(load_settings(path), (DEFAULTS, None))
            settings = {**DEFAULTS, 'theme': 'dark', 'sensitivity': 18}
            save_settings(path, settings)
            self.assertEqual(load_settings(path), (settings, None))
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_invalid_preferences_are_reported_and_not_overwritten(self):
        for contents in ('broken json', '[]', '{"sensitivity": true}', '{"extra": 1}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'settings.json'
                path.write_text(contents)
                settings, warning = load_settings(path)
                self.assertEqual(settings, DEFAULTS)
                self.assertIsNotNone(warning)
                self.assertEqual(path.read_text(), contents)

    def test_every_setting_is_validated(self):
        for key, (low, high) in RANGES.items():
            for value in (float('nan'), float('inf'), low-1, high+1, True, '12', None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate({**DEFAULTS, key: value})
        for key, value in (('theme', 'purple'), ('invert_x', 1), ('invert_y', None), ('roll_compensation', 'yes')):
            with self.assertRaises(ValueError):
                validate({**DEFAULTS, key: value})

    def test_command_carries_every_pointer_option(self):
        args = command({**DEFAULTS, 'invert_x': False, 'invert_y': True, 'roll_compensation': False})
        for key in RANGES:
            self.assertEqual(args[args.index('--'+key.replace('_', '-'))+1], str(DEFAULTS[key]))
        for flag in ('--watch', '--app-managed', '--no-invert-x', '--invert-y', '--no-roll-compensation'):
            self.assertIn(flag, args)
        self.assertNotIn('--theme', args)


class BackendTests(unittest.TestCase):
    def test_app_crash_stops_real_backend_and_releases_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, 'XDG_RUNTIME_DIR': directory}
            helper = '''
import os, time
from desktop_backend import Backend, DEFAULTS
backend = Backend()
backend.start(DEFAULTS)
for _ in range(200):
    backend.tick()
    if any('Waiting for the configured' in line for line in backend.logs):
        print(backend.process.pid, flush=True)
        os._exit(0)
    time.sleep(.01)
backend.close()
raise SystemExit('Backend did not reach waiting state')
'''
            parent = subprocess.run(['/usr/bin/python3', '-c', helper], env=environment,
                                    capture_output=True, text=True, timeout=8, check=True)
            pid = int(parent.stdout.strip())
            with open(Path(directory)/'wii-clicker.lock', 'a') as lock:
                deadline = time.monotonic()+4
                while time.monotonic() < deadline:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(.01)
                else:
                    os.kill(pid, signal.SIGKILL)
                    self.fail('Backend survived its desktop parent')

    def test_status_stream_handles_partial_lines_and_invalid_events(self):
        backend = Backend()
        backend.consume('log line\nWIIPOINTER {"state":"rea')
        self.assertEqual(backend.state, 'paused')
        backend.consume('dy","message":"Connected"}\nWIIPOINTER garbage\n')
        self.assertEqual((backend.state, backend.message), ('ready', 'Connected'))
        backend.consume('WIIPOINTER {"state":"bogus","message":"bad"}\n')
        self.assertEqual(backend.state, 'ready')
        backend.stopping_since = 1
        backend.consume('WIIPOINTER {"state":"waiting","message":"late"}\n')
        self.assertEqual(backend.state, 'ready')

    def test_pause_preserves_process_and_suppresses_late_ready_status(self):
        backend = Backend()
        self.assertFalse(backend.pause())
        backend.process = Mock()
        backend.state = 'ready'
        self.assertTrue(backend.pause())
        self.assertEqual(backend.state, 'paused')
        backend.consume('WIIPOINTER {"state":"ready","message":"Ready"}\n')
        self.assertEqual(backend.state, 'paused')
        self.assertTrue(backend.pause(False))
        self.assertEqual(backend.state, 'ready')
        backend.process.send_signal.assert_not_called()

    def test_spawn_error_is_visible(self):
        backend = Backend()
        with patch('desktop_backend.subprocess.Popen', side_effect=PermissionError('Denied')):
            backend.start(DEFAULTS)
        self.assertEqual(backend.state, 'error')
        self.assertIn('Denied', backend.message)

    def wait_for(self, backend, predicate):
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            backend.tick()
            if predicate():
                return
            time.sleep(.01)
        self.fail(f'Backend did not settle: {backend.state}: {backend.message}')

    def test_live_changes_and_pause_resume_keep_same_child(self):
        child = ['python3', '-u', '-c',
                 'import time; print(\'WIIPOINTER {"state":"ready","message":"Fake device"}\', flush=True); time.sleep(30)']
        backend = Backend()
        with patch('desktop_backend.command', return_value=child):
            try:
                backend.start(DEFAULTS)
                first = backend.process
                self.wait_for(backend, lambda: backend.state == 'ready')
                backend.start({**DEFAULTS, 'sensitivity': 20})
                backend.tick()
                self.assertIs(backend.process, first)
                self.assertIsNone(first.poll())
                backend.pause()
                backend.tick()
                self.assertEqual(backend.state, 'paused')
                backend.start(DEFAULTS)
                self.assertIs(backend.process, first)
                self.assertEqual(backend.state, 'ready')
                backend.stop()
                self.wait_for(backend, lambda: backend.process is None)
                self.assertEqual(backend.state, 'paused')
                backend.start(DEFAULTS)
                self.wait_for(backend, lambda: backend.state == 'ready')
                last = backend.process
            finally:
                backend.close()
            self.assertIsNotNone(last.poll())

    def test_unexpected_exit_keeps_final_error(self):
        backend = Backend()
        with patch('desktop_backend.command', return_value=['python3', '-c', 'raise SystemExit("Permission denied")']):
            backend.start(DEFAULTS)
            self.wait_for(backend, lambda: backend.process is None)
        self.assertEqual(backend.state, 'error')
        self.assertIn('Permission denied', backend.message)

    def test_updates_coalesce_without_restarting_or_blocking(self):
        backend = Backend()
        with patch('desktop_backend.command', return_value=['sleep', '30']):
            try:
                backend.start(DEFAULTS)
                first = backend.process
                for value in range(1, 30):
                    backend.update({**DEFAULTS, 'sensitivity': value})
                self.assertEqual(len(backend.commands), 1)
                self.assertIs(backend.process, first)
                backend.stop()
                self.wait_for(backend, lambda: backend.process is None)
                self.assertEqual(backend.state, 'paused')
            finally:
                backend.close()

    def test_real_backend_waits_without_controller_and_obeys_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_RUNTIME_DIR=directory):
            import fcntl
            lock = open(Path(directory)/'wii-clicker.lock', 'a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            backend = Backend()
            try:
                backend.start(DEFAULTS)
                self.wait_for(backend, lambda: backend.process is None)
                self.assertEqual(backend.state, 'error')
                self.assertIn('Another WiiPointer backend', backend.message)
                lock.close()
                backend.start(DEFAULTS)
                self.wait_for(backend, lambda: any('Waiting for the configured' in log for log in backend.logs))
                self.assertEqual(backend.state, 'waiting')
            finally:
                lock.close()
                backend.close()


if __name__ == '__main__':
    unittest.main()
