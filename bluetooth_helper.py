"""Small asynchronous BlueZ client for the connection helper."""
import gi
from gi.repository import Gio, GLib


def connection_info(objects, address):
    adapters, remotes = [], []
    selected = None
    for path, interfaces in objects.items():
        if 'org.bluez.Adapter1' in interfaces:
            adapters.append((path, interfaces['org.bluez.Adapter1']))
        device = interfaces.get('org.bluez.Device1')
        if device:
            name = device.get('Alias', device.get('Name', 'Wii Remote'))
            if device.get('Address', '').lower() == address.lower():
                selected = (path, device)
            if any(word in name.lower() for word in ('nintendo', 'rvl-cnt', 'wii')) or (selected and selected[0] == path):
                remotes.append((device.get('Address', ''), name))
    adapter = next((item for item in adapters if selected and selected[1].get('Adapter') == item[0]), None)
    adapter = adapter or next((item for item in adapters if item[1].get('Powered')), adapters[0] if adapters else None)
    if not adapter:
        message = 'No Bluetooth adapter found. Check that Bluetooth is available on this laptop.'
    elif not adapter[1].get('Powered'):
        message = 'Bluetooth is off. Turn it on, then wake your remote.'
    elif selected is None:
        message = 'Remote not found. Scan while holding 1 + 2, or press the red SYNC button, then pair in Bluetooth settings.'
    elif not selected[1].get('Paired'):
        message = 'Remote found but not paired. Open Bluetooth settings to finish pairing.'
    elif not selected[1].get('Connected'):
        message = 'Remote is paired. Press A to wake it, or hold 1 + 2 while choosing Connect.'
    else:
        message = 'Bluetooth connected. WiiPointer is waiting for usable kernel input and MotionPlus interfaces.'
    return dict(adapter=adapter, selected=selected, remotes=sorted(remotes), message=message)


class ConnectionHelper:
    def __init__(self):
        self.bus = None
        self.info = None
        self.scanning_adapter = None
        self.closed = False

    def refresh(self, address, callback):
        def bus_ready(_source, result):
            try:
                self.bus = Gio.bus_get_finish(result)
            except GLib.Error as exc:
                callback(None, str(exc))
                return
            self.call('/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', None,
                      lambda result, error: finished(result, error))

        def finished(result, error):
            if self.closed:
                return
            if error:
                callback(None, error)
            else:
                self.info = connection_info(result[0], address)
                callback(self.info, None)

        Gio.bus_get(Gio.BusType.SYSTEM, None, bus_ready)

    def call(self, path, interface, method, parameters, callback):
        if self.bus is None:
            callback(None, 'Bluetooth is unavailable. Refresh the connection helper first.')
            return
        def finished(connection, result):
            try:
                value = connection.call_finish(result).unpack()
            except GLib.Error as exc:
                callback(None, str(exc))
            else:
                callback(value, None)
        self.bus.call('org.bluez', path, interface, method, parameters, None,
                      Gio.DBusCallFlags.NONE, 15000, None, finished)

    def power_on(self, callback):
        adapter = self.info and self.info['adapter']
        if not adapter:
            callback(None, 'No Bluetooth adapter is available.')
            return
        self.call(adapter[0], 'org.freedesktop.DBus.Properties', 'Set',
                  GLib.Variant('(ssv)', ('org.bluez.Adapter1', 'Powered', GLib.Variant('b', True))), callback)

    def connect_remote(self, callback):
        selected = self.info and self.info['selected']
        if not selected or not selected[1].get('Paired'):
            callback(None, 'Pair this remote in GNOME Bluetooth settings first.')
            return
        self.call(selected[0], 'org.bluez.Device1', 'Connect', None, callback)

    def scan(self, callback):
        adapter = self.info and self.info['adapter']
        if not adapter or not adapter[1].get('Powered'):
            callback(None, 'Turn Bluetooth on before scanning.')
            return
        if self.scanning_adapter:
            callback((), None)
            return
        path = adapter[0]
        def started(value, error):
            if error is None:
                self.scanning_adapter = path
                if self.closed:
                    self.close()
            callback(value, error)
        self.call(path, 'org.bluez.Adapter1', 'StartDiscovery', None, started)

    def close(self):
        self.closed = True
        if self.scanning_adapter:
            path, self.scanning_adapter = self.scanning_adapter, None
            self.call(path, 'org.bluez.Adapter1', 'StopDiscovery', None, lambda *_: None)
