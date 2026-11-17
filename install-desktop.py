#!/usr/bin/python3
"""Install the desktop entry and replace the legacy login-started service."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent


def install():
    # Check dependencies before changing the existing service.
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('AyatanaAppIndicator3', '0.1')
    import evdev
    import cairo
    binary = Path.home()/'.local/bin'
    binary.mkdir(parents=True, exist_ok=True)
    for name in ('wiipointer', 'wii-clicker'):
        target = binary/name
        if (target.exists() or target.is_symlink()) and not (target.is_symlink() and target.resolve() == ROOT/name):
            raise RuntimeError(f'Refusing to overwrite {target}; move it aside first.')
    loaded = subprocess.run(['systemctl', '--user', 'show', 'wii-clicker.service',
                             '--property=LoadState', '--value'], check=True, capture_output=True, text=True)
    if loaded.stdout.strip() != 'not-found':
        subprocess.run(['systemctl', '--user', 'disable', '--now', 'wii-clicker.service'], check=True)
    for name in ('wiipointer', 'wii-clicker'):
        source, target = ROOT/name, binary/name
        source.chmod(source.stat().st_mode | 0o111)
        if target.is_symlink() and target.resolve() == source:
            continue
        if target.exists() or target.is_symlink():
            raise RuntimeError(f'Refusing to overwrite {target}; move it aside first.')
        target.symlink_to(source)
    applications = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'applications'
    applications.mkdir(parents=True, exist_ok=True)
    # Desktop Exec fields interpret percent escapes, quotes, backslashes and dollars.
    executable = str(ROOT/'wiipointer').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    (applications/'io.github.wiipointer.Desktop.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=WiiPointer\n'
        'Comment=Wii Remote air mouse and presentation companion\n'
        f'Exec="{executable}"\nIcon={ROOT/"wiipointer.svg"}\n'
        'Terminal=false\nCategories=Utility;\nStartupNotify=true\n'
        'StartupWMClass=io.github.wiipointer.Desktop\n')
    print('Installed WiiPointer. Launch it from Activities or run wiipointer.\n'
          'The old login service is disabled; controller input now belongs to the app.')


if __name__ == '__main__':
    install()
