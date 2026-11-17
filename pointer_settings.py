"""Settings shared by the desktop app and controller process."""

from copy import deepcopy
import math
import re

DEFAULT_MAPPINGS = {'A': 'left_click', 'B': 'aim', 'Up': 'page_up', 'Down': 'page_down',
                    'Left': 'page_up', 'Right': 'page_down', '+': 'volume_up',
                    '-': 'volume_down', 'HOME': 'desktop', '1': 'overview', '2': 'quick_settings'}
ACTIONS = {'aim': 'Hold to aim', 'left_click': 'Left click / drag', 'right_click': 'Right click',
           'middle_click': 'Middle click', 'page_up': 'Previous slide', 'page_down': 'Next slide',
           'volume_up': 'Volume up', 'volume_down': 'Volume down', 'desktop': 'Show desktop',
           'overview': 'Activities overview', 'quick_settings': 'GNOME quick settings',
           'none': 'Disabled'}
DEFAULTS = dict(sensitivity=12., smoothing=.025, deadzone=.3, acceleration=.3,
                invert_x=True, invert_y=False, roll_compensation=True, theme='light',
                remote_mac='2C:10:C1:DF:A8:54', mappings=DEFAULT_MAPPINGS)
RANGES = dict(sensitivity=(1, 30), smoothing=(0, .1), deadzone=(0, 3), acceleration=(0, 1))


def default_settings():
    return deepcopy(DEFAULTS)


def validate(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULTS):
        raise ValueError('Invalid settings keys')
    for key, (low, high) in RANGES.items():
        value = settings[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Invalid {key}')
    for key in ('invert_x', 'invert_y', 'roll_compensation'):
        if type(settings[key]) is not bool:
            raise ValueError(f'Invalid {key}')
    if settings['theme'] not in ('light', 'dark', 'system'):
        raise ValueError('Invalid theme')
    if not isinstance(settings['remote_mac'], str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', settings['remote_mac']):
        raise ValueError('Enter a Bluetooth address such as 2C:10:C1:DF:A8:54')
    mappings = settings['mappings']
    if not isinstance(mappings, dict) or set(mappings) != set(DEFAULT_MAPPINGS):
        raise ValueError('Invalid button mappings')
    if any(not isinstance(action, str) or action not in ACTIONS for action in mappings.values()):
        raise ValueError('Unknown button action')
    if mappings['HOME'] == 'aim':
        raise ValueError('HOME is reserved for tap actions and long-press calibration')
    if 'aim' not in mappings.values() or 'left_click' not in mappings.values():
        raise ValueError('Keep at least one Hold to aim and one Left click mapping')
    return settings
