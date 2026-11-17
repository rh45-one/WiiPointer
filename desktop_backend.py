"""Desktop preferences and the app-owned controller process (no GUI imports)."""

from collections import deque
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from pointer_settings import DEFAULTS, RANGES, default_settings, validate

ROOT = Path(__file__).resolve().parent


def load_settings(path):
    try:
        return validate({**default_settings(), **json.loads(path.read_text())}), None
    except FileNotFoundError:
        return default_settings(), None
    except (OSError, ValueError, TypeError) as exc:
        return default_settings(), f'Could not load preferences: {exc}. Defaults are in use.'


def save_settings(path, settings):
    validate(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, indent=2) + '\n')
    temporary.replace(path)


def command(settings):
    validate(settings)
    args = ['/usr/bin/python3', '-u', str(ROOT/'wii_mouse.py'), '--watch', '--app-managed',
            '--app-parent', str(os.getpid())]
    for key in RANGES:
        args.extend(('--' + key.replace('_', '-'), str(settings[key])))
    args.append('--invert-x' if settings['invert_x'] else '--no-invert-x')
    if settings['invert_y']:
        args.append('--invert-y')
    args.append('--roll-compensation' if settings['roll_compensation'] else '--no-roll-compensation')
    args.extend(('--remote-mac', settings['remote_mac']))
    return args


class Backend:
    def __init__(self):
        self.process = None
        self.state = 'paused'
        self.message = 'Controller input is paused.'
        self.logs = deque(maxlen=200)
        self.buffer = ''
        self.stopping_since = None
        self.paused = False
        self.previous_state = ('waiting', 'Waiting for the remote.')
        self.commands = {}
        self.outgoing = b''

    def start(self, settings):
        if self.process is not None:
            self.update(settings)
            self.pause(False)
            return
        self.buffer = ''
        self.commands.clear()
        self.outgoing = b''
        self.stopping_since = None
        try:
            self.process = subprocess.Popen(command(settings), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, start_new_session=True)
            os.set_blocking(self.process.stdout.fileno(), False)
            os.set_blocking(self.process.stdin.fileno(), False)
        except OSError as exc:
            self.state, self.message = 'error', str(exc)
            return
        self.state, self.message = 'waiting', 'Press A on your paired Wii Remote, then set it down.'
        self.previous_state = self.state, self.message
        self.paused = False
        self.update(settings)

    def send(self, event):
        if not self.process or self.stopping_since is not None:
            return False
        self.commands[event['type']] = (json.dumps(event)+'\n').encode()
        return True

    def update(self, settings):
        return self.send({'type': 'settings', 'settings': validate(settings)})

    def pause(self, paused=True):
        if not self.send({'type': 'pause', 'paused': paused}):
            return False
        if paused and not self.paused:
            self.previous_state = self.state, self.message
        self.paused = paused
        self.state, self.message = ('paused', 'Controller input is paused.') if paused else self.previous_state
        return True

    def stop(self):
        if self.process and self.stopping_since is None:
            self.stopping_since = time.monotonic()
            try:
                self.process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.state, self.message = 'stopping', 'Releasing controller input…'
        elif not self.process:
            self.state, self.message = 'paused', 'Controller input is paused.'

    def consume(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self.logs.append(line)
            if line.startswith('WIIPOINTER ') and self.stopping_since is None:
                try:
                    event = json.loads(line[len('WIIPOINTER '):])
                    if event['state'] in ('waiting', 'calibrating', 'ready') and isinstance(event['message'], str):
                        self.previous_state = event['state'], event['message']
                        if not self.paused:
                            self.state, self.message = self.previous_state
                except (ValueError, KeyError, TypeError):
                    pass

    def tick(self):
        if not self.process:
            return
        if not self.outgoing:
            self.outgoing = b''.join(self.commands.values())
            self.commands.clear()
        if self.outgoing:
            try:
                count = os.write(self.process.stdin.fileno(), self.outgoing)
                self.outgoing = self.outgoing[count:]
            except (BlockingIOError, BrokenPipeError):
                pass
        try:
            data = os.read(self.process.stdout.fileno(), 65536)
            self.consume(data.decode('utf-8', errors='replace'))
        except BlockingIOError:
            pass
        code = self.process.poll()
        if code is None:
            if self.stopping_since is not None and time.monotonic()-self.stopping_since > 5:
                self.process.kill()
            return
        # Drain any final diagnostics before closing the pipe.
        self.consume(self.process.stdout.read().decode('utf-8', errors='replace'))
        if self.buffer:
            self.logs.append(self.buffer)
            self.buffer = ''
        self.process.stdout.close()
        self.process.stdin.close()
        self.process = None
        if self.stopping_since is None:
            self.state = 'error'
            self.message = self.logs[-1] if self.logs else f'Controller service exited ({code}).'
        else:
            self.state, self.message = 'paused', 'Controller input is paused.'
        self.stopping_since = None

    def close(self):
        self.stop()
        if self.process:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdout.close()
            self.process.stdin.close()
            self.process = None
