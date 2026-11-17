#!/usr/bin/python3
"""WiiPointer's native desktop shell. The backend exists only while this app does."""

from datetime import datetime
import os
from pathlib import Path
import signal
import sys

import gi
import cairo
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import AyatanaAppIndicator3, Gdk, Gio, GLib, Gtk

from desktop_backend import Backend, DEFAULTS, ROOT, load_settings, save_settings
from pointer_settings import ACTIONS, DEFAULT_MAPPINGS, RANGES, validate
from bluetooth_helper import ConnectionHelper

CSS = """
window, .dialog-vbox { background: @base; color: @ink; }
* { font-family: 'Cantarell', sans-serif; font-size: 14px; }
.shell { background-image: linear-gradient(to bottom, @top, @base); }
.brand { font-size: 26px; font-weight: 300; letter-spacing: -1px; }
.eyebrow { font-size: 11px; font-weight: bold; letter-spacing: 2px; color: @muted; }
.muted { color: @muted; }
.headline { font-size: 26px; font-weight: 300; }
.channel { border: 2px solid @edge; border-radius: 20px;
 background-image: linear-gradient(to bottom, @cardtop, @cardbottom);
 box-shadow: 0 3px 0 alpha(@shadow,.12), inset 0 1px 0 alpha(white,.65);
 padding: 18px; color: @ink; transition: 150ms ease; }
.channel:hover { border-color: #39bce4; box-shadow: 0 0 0 3px alpha(#39bce4,.13); }
.channel:focus { outline: 2px solid #079fc9; outline-offset: 3px; }
.channel:active { background-image: linear-gradient(to bottom, @cardbottom, @cardtop); }
.channel-title { font-size: 18px; font-weight: bold; }
.channel-note { color: @muted; font-size: 12px; }
.status-pill { border: 1px solid @edge; border-radius: 20px; padding: 8px 14px;
 background: alpha(@cardtop,.8); color: @muted; font-size: 12px; }
.footer { padding: 30px 24px 16px; background: transparent; }
.clock { font-family: 'DejaVu Sans Mono', monospace; font-size: 32px; font-weight: 300; color: @muted; }
.round { border-radius: 28px; border: 2px solid #78ccde; padding: 10px 18px;
 background-image: linear-gradient(to bottom, @cardtop, @cardbottom); color: @ink; }
button.suggested-action { background: #079fc9; color: white; border: 1px solid #008db8; border-radius: 12px; padding: 8px 18px; }
scale trough { min-height: 5px; border-radius: 5px; }
scale highlight, switch:checked { background: #13a9d6; }
textview text { background: @cardtop; color: @ink; font-family: monospace; font-size: 12px; }
"""
PALETTES = {
    'light': dict(base='#e6e9e9', top='#f5f6f4', ink='#39484e', muted='#6b7a80',
                  edge='#c6cece', cardtop='#ffffff', cardbottom='#e6ebeb', shadow='#50636b'),
    'dark': dict(base='#171f27', top='#25313b', ink='#e9f2f6', muted='#a3b5c1',
                 edge='#465561', cardtop='#35434f', cardbottom='#26323d', shadow='#000000'),
}


def label(text, css=None):
    widget = Gtk.Label(label=text)
    if css:
        widget.get_style_context().add_class(css)
    return widget


class WiiPointer(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.wiipointer.Desktop',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
        self.settings_path = config/'wiipointer'/'settings.json'
        self.settings, self.settings_warning = load_settings(self.settings_path)
        self.backend = Backend()
        self.window = None
        self.quitting = False
        self.apply_source = None
        self.preferences_window = None
        self.connection_window = None
        self.provider = Gtk.CssProvider()
        self.system_appearance = Gio.Settings.new('org.gnome.desktop.interface')
        self.system_appearance.connect('changed::color-scheme', lambda *_: self.apply_theme())

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            'wiipointer', str(ROOT/'wiipointer.svg'),
            AyatanaAppIndicator3.IndicatorCategory.HARDWARE)
        self.indicator.set_title('WiiPointer')
        menu = Gtk.Menu()
        self.tray_status = Gtk.MenuItem(label='WiiPointer · Waiting for remote')
        self.tray_status.set_sensitive(False)
        menu.append(self.tray_status)
        self.menu_item(menu, 'Open WiiPointer', self.present_window)
        menu.append(Gtk.SeparatorMenuItem())
        self.pause_item = self.menu_item(menu, 'Pause controller input', self.toggle_backend)
        self.menu_item(menu, 'Pointer settings…', self.preferences)
        self.menu_item(menu, 'Button mappings…', self.button_mappings)
        self.menu_item(menu, 'Connection helper…', self.connection)
        self.dark_item = Gtk.CheckMenuItem(label='Dark appearance')
        self.dark_item.set_active(self.settings['theme'] == 'dark')
        self.dark_item.connect('toggled', self.toggle_dark)
        menu.append(self.dark_item)
        menu.append(Gtk.SeparatorMenuItem())
        self.menu_item(menu, 'Quit WiiPointer', self.quit_app)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.apply_theme()
        Gtk.Settings.get_default().connect('notify::gtk-theme-name', lambda *_: self.apply_theme())
        self.backend.start(self.settings)
        GLib.timeout_add(150, self.refresh)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit_app)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit_app)

    def menu_item(self, menu, title, callback):
        item = Gtk.MenuItem(label=title)
        item.connect('activate', lambda *_: callback())
        menu.append(item)
        return item

    def do_activate(self):
        self.present_window()

    def present_window(self):
        if self.window is None:
            self.build_window()
        self.window.show_all()
        self.window.present()
        if self.settings_warning:
            warning, self.settings_warning = self.settings_warning, None
            self.message('Preferences notice', warning)

    def build_window(self):
        self.window = Gtk.ApplicationWindow(application=self, title='WiiPointer')
        self.window.set_default_size(960, 700)
        self.window.set_size_request(760, 600)
        self.window.set_icon_from_file(str(ROOT/'wiipointer.svg'))
        self.window.connect('delete-event', self.close_window)
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shell.get_style_context().add_class('shell')
        self.window.add(shell)
        header = Gtk.Box(spacing=12, margin=28)
        wordmark = label('WiiPointer', 'brand')
        header.pack_start(wordmark, False, False, 0)
        header.pack_start(label('MOTION, MEET DESKTOP', 'eyebrow'), True, True, 0)
        self.status_label = label('', 'status-pill')
        header.pack_end(self.status_label, False, False, 0)
        shell.pack_start(header, False, False, 0)
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=32, margin_end=32)
        title = label('A little Wii. A whole new desktop.', 'headline')
        title.set_xalign(0)
        intro.pack_start(title, False, False, 0)
        self.detail_label = label('', 'muted')
        self.detail_label.set_xalign(0)
        self.detail_label.set_line_wrap(True)
        self.detail_label.set_max_width_chars(80)
        intro.pack_start(self.detail_label, False, False, 0)
        shell.pack_start(intro, False, False, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True,
                        row_homogeneous=True, margin=28)
        self.connect_button, self.connect_title = self.channel(
            'Wii Remote', 'Connection helper · pause · resume', self.connection)
        mappings, _ = self.channel('Button mappings', 'Choose what each button does', self.button_mappings)
        pointer, _ = self.channel('Pointer', 'Make every movement yours', self.preferences)
        controls, _ = self.channel('Button guide', 'Your desktop, at your fingertips', self.controls)
        appearance, _ = self.channel('Appearance', 'Light, dark, or follow your system', lambda: self.preferences('appearance'))
        diagnostics, _ = self.channel('Connection details', 'Live status & service activity', self.diagnostics)
        for i, widget in enumerate((self.connect_button, mappings, pointer,
                                    controls, appearance, diagnostics)):
            grid.attach(widget, i % 3, i // 3, 1, 1)
        shell.pack_start(grid, True, True, 0)
        footer = Gtk.Box(spacing=20)
        footer.get_style_context().add_class('footer')
        footer.connect('draw', self.draw_footer)
        tray = Gtk.Button(label='Hide to tray', tooltip_text='Hide to tray (controller stays available)')
        tray.get_style_context().add_class('round')
        tray.connect('clicked', lambda *_: self.close_window())
        footer.pack_start(tray, False, False, 0)
        clock_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.clock = label('', 'clock')
        self.date = label('', 'muted')
        clock_box.pack_start(self.clock, False, False, 0)
        clock_box.pack_start(self.date, False, False, 0)
        footer.pack_start(clock_box, True, True, 0)
        quit_button = Gtk.Button(label='Quit', tooltip_text='Quit the app and stop controller input')
        quit_button.get_style_context().add_class('round')
        quit_button.connect('clicked', lambda *_: self.quit_app())
        footer.pack_end(quit_button, False, False, 0)
        shell.pack_end(footer, False, False, 0)
        self.refresh()

    def channel(self, title, subtitle, callback):
        button = Gtk.Button()
        button.get_style_context().add_class('channel')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        artwork = Gtk.DrawingArea()
        artwork.set_size_request(96, 74)
        artwork.connect('draw', self.draw_channel, title)
        box.pack_start(artwork, True, True, 0)
        heading = label(title, 'channel-title')
        box.pack_start(heading, False, False, 0)
        box.pack_start(label(subtitle, 'channel-note'), False, False, 0)
        button.add(box)
        button.connect('clicked', lambda *_: callback())
        button.get_accessible().set_name(title)
        return button, heading

    def draw_footer(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        dark = Gtk.Settings.get_default().get_property('gtk-application-prefer-dark-theme')
        cr.move_to(0, 1)
        cr.line_to(width*.12, 1)
        cr.curve_to(width*.24, 1, width*.23, 23, width*.36, 23)
        cr.line_to(width*.64, 23)
        cr.curve_to(width*.77, 23, width*.76, 1, width*.88, 1)
        cr.line_to(width, 1)
        cr.line_to(width, height)
        cr.line_to(0, height)
        cr.close_path()
        cr.set_source_rgb(*((.12, .17, .21) if dark else (.88, .91, .92)))
        cr.fill_preserve()
        cr.set_source_rgba(.22, .72, .85, .65)
        cr.set_line_width(2)
        cr.stroke()
        return False

    def draw_channel(self, widget, cr, title):
        """Small vector channel illustrations, sharp at any desktop scale."""
        cr.translate(widget.get_allocated_width()/2, widget.get_allocated_height()/2)
        cr.set_line_width(2.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_source_rgb(.06, .65, .82)
        if title == 'Wii Remote':
            cr.rotate(-.3)
            cr.rectangle(-15, -35, 30, 68)
            cr.stroke()
            cr.move_to(-8, -17); cr.line_to(8, -17)
            cr.move_to(0, -25); cr.line_to(0, -9)
            cr.stroke()
            cr.arc(0, 3, 6, 0, 6.284); cr.stroke()
            for y in (18, 26):
                cr.arc(0, y, 2, 0, 6.284); cr.fill()
            for x in (-9, -3, 3, 9):
                cr.rectangle(x-1, 38, 3, 3); cr.fill()
        elif title == 'Calibration':
            for radius in (12, 27):
                cr.arc(0, 0, radius, 0, 6.284); cr.stroke()
            for x, y in ((-35, 0), (35, 0), (0, -35), (0, 35)):
                cr.move_to(x, y); cr.line_to(x*.65, y*.65); cr.stroke()
            cr.arc(0, 0, 3, 0, 6.284); cr.fill()
        elif title == 'Pointer':
            cr.move_to(-20, -30); cr.line_to(28, 7); cr.line_to(7, 11)
            cr.line_to(-4, 32); cr.close_path()
            cr.set_source_rgba(.06, .65, .82, .14); cr.fill_preserve()
            cr.set_source_rgb(.06, .65, .82); cr.stroke()
            for i in (0, 1):
                cr.move_to(13+i*10, -25-i*4); cr.line_to(17+i*10, -32-i*4); cr.stroke()
        elif title in ('Button guide', 'Button mappings'):
            points = [(-10, -30), (10, -30), (10, -10), (30, -10), (30, 10),
                      (10, 10), (10, 30), (-10, 30), (-10, 10), (-30, 10), (-30, -10), (-10, -10)]
            cr.move_to(*points[0])
            for point in points[1:]:
                cr.line_to(*point)
            cr.close_path(); cr.stroke()
            cr.arc(0, 0, 4, 0, 6.284); cr.fill()
        elif title == 'Appearance':
            cr.arc(0, 0, 29, 0, 6.284); cr.stroke()
            cr.arc(0, 0, 23, -1.5708, 1.5708); cr.close_path(); cr.fill()
        else:
            for i, height in enumerate((18, 38, 58, 43, 27)):
                cr.move_to(-28+i*14, height/2)
                cr.line_to(-28+i*14, -height/2)
                cr.stroke()
        return False

    def close_window(self, *_):
        if self.indicator.get_status() == AyatanaAppIndicator3.IndicatorStatus.ACTIVE and self.indicator.get_property('connected'):
            for dialog in Gtk.Window.list_toplevels():
                if isinstance(dialog, Gtk.Dialog) and dialog.get_transient_for() == self.window:
                    dialog.destroy()
            if self.window:
                self.window.hide()
        else:
            self.message('Tray unavailable', 'GNOME needs the AppIndicator and KStatusNotifierItem Support extension to show tray icons. The window will stay open so you can still access WiiPointer. Use Quit to stop the app.')
        return True

    def apply_theme(self):
        theme = self.settings['theme']
        gtk_settings = Gtk.Settings.get_default()
        dark = theme == 'dark' or (theme == 'system' and (
            self.system_appearance.get_string('color-scheme') == 'prefer-dark' or
            'dark' in gtk_settings.get_property('gtk-theme-name').lower()))
        gtk_settings.set_property('gtk-application-prefer-dark-theme', dark)
        palette = '\n'.join(f'@define-color {key} {value};' for key, value in PALETTES['dark' if dark else 'light'].items())
        self.provider.load_from_data((palette + CSS).encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def toggle_dark(self, item):
        self.settings['theme'] = 'dark' if item.get_active() else 'light'
        self.persist(update=False)
        self.apply_theme()
        if self.preferences_window:
            self.preferences_window.destroy()

    def persist(self, update=True):
        try:
            save_settings(self.settings_path, self.settings)
        except OSError as exc:
            self.message('Could not save preferences', str(exc))
        if update:
            if self.apply_source:
                GLib.source_remove(self.apply_source)
            self.apply_source = GLib.timeout_add(150, self.apply_settings)

    def apply_settings(self):
        self.apply_source = None
        self.backend.update(self.settings)
        return False

    def dialog(self, title, width=500):
        dialog = Gtk.Dialog(title=title, transient_for=self.window, destroy_with_parent=True)
        dialog.set_default_size(width, -1)
        dialog.add_button('Done', Gtk.ResponseType.CLOSE)
        dialog.connect('response', lambda d, *_: d.destroy())
        content = dialog.get_content_area()
        content.set_spacing(16)
        content.set_border_width(24)
        return dialog, content

    def message(self, title, text):
        self.present_if_needed()
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                                   text=title)
        dialog.format_secondary_text(text)
        dialog.connect('response', lambda d, *_: d.destroy())
        dialog.show_all()

    def present_if_needed(self):
        if self.window is None:
            self.build_window()
        self.window.show_all()

    def connection(self):
        self.present_if_needed()
        if self.connection_window:
            self.connection_window.present()
            return
        dialog, box = self.dialog('Connection helper', 620)
        self.connection_window = dialog
        helper = ConnectionHelper()
        heading = label('Connect your Wii Remote', 'channel-title')
        box.add(heading)
        instructions = label('1. Turn Bluetooth on.\n2. For a paired remote, press A. To pair, hold 1 + 2 or press SYNC.\n3. Put the remote on a table for its initial calibration.\n\nAfter that, only holding HOME recalibrates. Settings apply live.')
        instructions.set_line_wrap(True)
        instructions.set_max_width_chars(68)
        box.add(instructions)
        status = label('Checking Bluetooth…', 'muted')
        status.set_line_wrap(True)
        status.set_max_width_chars(65)
        box.add(status)
        remotes = Gtk.ComboBoxText()
        remotes.append('', 'Choose a discovered Wii Remote…')
        remotes.set_active_id('')
        address = Gtk.Entry(text=self.settings['remote_mac'], placeholder_text='Bluetooth address')
        address.get_accessible().set_name('Remote Bluetooth address')
        remotes.connect('changed', lambda combo: address.set_text(combo.get_active_id()) if combo.get_active_id() else None)
        box.add(remotes)
        row = Gtk.Box(spacing=12)
        row.pack_start(address, True, True, 0)
        use = Gtk.Button(label='Use this remote')
        row.pack_end(use, False, False, 0)
        box.add(row)
        activity = label('', 'muted')
        activity.set_line_wrap(True)
        activity.set_max_width_chars(65)
        box.add(activity)
        busy, known = [False], [None]

        def received(info, error):
            busy[0] = False
            if helper.closed:
                return
            status.set_text(error or info['message'])
            if info and info['remotes'] != known[0]:
                known[0] = info['remotes']
                remotes.remove_all()
                remotes.append('', 'Choose a discovered Wii Remote…')
                for mac, name in info['remotes']:
                    remotes.append(mac, f'{name} ({mac})')
                remotes.set_active_id('')

        def refresh():
            if helper.closed:
                return False
            if not busy[0]:
                busy[0] = True
                helper.refresh(self.settings['remote_mac'], received)
            pause.set_label('Resume input' if self.backend.state in ('paused', 'error') else 'Pause input')
            return True

        def completed(_result, error):
            if not helper.closed:
                activity.set_text(error or 'Request sent. Watch the connection status above.')
                refresh()

        def use_remote(*_):
            candidate = {**self.settings, 'remote_mac': address.get_text().strip().upper()}
            try:
                validate(candidate)
            except ValueError as exc:
                activity.set_text(str(exc))
                return
            changed = candidate['remote_mac'].lower() != self.settings['remote_mac'].lower()
            if changed:
                candidate['roll_compensation'] = False
            self.settings = candidate
            self.persist()
            activity.set_text('Remote selected. Roll compensation is off until you measure this remote’s accelerometer; see the hardware guide.' if changed else 'This remote is already selected.')
            refresh()

        use.connect('clicked', use_remote)
        actions = Gtk.Box(spacing=8, homogeneous=True)
        for title, action in (('Turn Bluetooth on', helper.power_on), ('Scan for remotes', helper.scan),
                              ('Connect', helper.connect_remote)):
            button = Gtk.Button(label=title)
            button.connect('clicked', lambda _button, callback=action: callback(completed))
            actions.add(button)
        box.add(actions)
        bluetooth = Gtk.Button(label='Pair or troubleshoot in Bluetooth settings')
        bluetooth.connect('clicked', lambda *_: self.bluetooth_settings())
        box.add(bluetooth)
        pause = Gtk.Button(label='Pause input')
        pause.connect('clicked', lambda *_: (self.toggle_backend(), refresh()))
        box.add(pause)
        permissions = label('Input permissions: ' + ('uinput is accessible.' if os.access('/dev/uinput', os.R_OK | os.W_OK) else 'uinput is not accessible; see README setup.'), 'muted')
        box.add(permissions)
        source = GLib.timeout_add(1500, refresh)
        def closed(*_):
            helper.close()
            GLib.source_remove(source)
            self.connection_window = None
        dialog.connect('destroy', closed)
        refresh()
        dialog.show_all()

    def bluetooth_settings(self):
        try:
            Gio.Subprocess.new(['gnome-control-center', 'bluetooth'], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.message('Bluetooth settings unavailable', str(exc))

    def toggle_backend(self):
        if self.apply_source:
            GLib.source_remove(self.apply_source)
            self.apply_source = None
        if self.backend.state in ('paused', 'error'):
            self.backend.start(self.settings)
        else:
            self.backend.pause()
        self.refresh()

    def preferences(self, page='pointer'):
        self.present_if_needed()
        if self.preferences_window:
            self.preferences_window.present()
            return
        dialog, content = self.dialog('WiiPointer settings', 560)
        self.preferences_window = dialog
        dialog.connect('destroy', lambda *_: setattr(self, 'preferences_window', None))
        notebook = Gtk.Notebook()
        content.add(notebook)
        pointer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=20)
        note = label('Changes save and apply live. Your calibration stays unchanged.\nHold HOME when you want to recalibrate.', 'muted')
        pointer.add(note)
        for key, title, low, high, step, factor, digits in (
                ('sensitivity', 'Sensitivity · pixels / degree', 1, 30, 1, 1, 0),
                ('smoothing', 'Smoothing · milliseconds', 0, 100, 1, 1000, 0),
                ('deadzone', 'Deadzone · degrees / second', 0, 3, .1, 1, 1),
                ('acceleration', 'Pointer acceleration · strength', 0, 1, .05, 1, 2)):
            pointer.add(label(title))
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
            scale.set_digits(digits)
            scale.get_accessible().set_name(title)
            scale.set_value(self.settings[key]*factor)
            scale.connect('value-changed', self.scale_changed, key, factor)
            pointer.add(scale)
        for key, title in (('invert_x', 'Invert horizontal movement'), ('invert_y', 'Invert vertical movement'),
                           ('roll_compensation', 'Compensate for controller roll')):
            row = Gtk.Box(spacing=20)
            row.pack_start(label(title), True, True, 0)
            switch = Gtk.Switch(active=self.settings[key])
            switch.get_accessible().set_name(title)
            switch.connect('notify::active', self.switch_changed, key)
            row.pack_end(switch, False, False, 0)
            pointer.add(row)
        reset = Gtk.Button(label='Restore pointer defaults')
        reset.connect('clicked', lambda *_: self.reset_pointer(dialog))
        pointer.add(reset)
        pointer_scroll = Gtk.ScrolledWindow()
        pointer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        pointer_scroll.set_min_content_height(410)
        pointer_scroll.add(pointer)
        notebook.append_page(pointer_scroll, label('Pointer'))
        appearance = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, margin=24)
        appearance.add(label('Choose your channel menu', 'channel-title'))
        combo = Gtk.ComboBoxText()
        for key, title in (('light', 'Wii Light'), ('dark', 'Midnight Wii'), ('system', 'Follow system theme')):
            combo.append(key, title)
        combo.set_active_id(self.settings['theme'])
        combo.connect('changed', self.theme_changed)
        appearance.add(combo)
        appearance.add(label('The same familiar channels. A softer glow after dark.', 'muted'))
        notebook.append_page(appearance, label('Appearance'))
        dialog.show_all()
        notebook.set_current_page(1 if page == 'appearance' else 0)

    def scale_changed(self, scale, key, factor):
        self.settings[key] = scale.get_value()/factor
        self.persist()

    def switch_changed(self, switch, _spec, key):
        self.settings[key] = switch.get_active()
        self.persist()

    def theme_changed(self, combo):
        self.settings['theme'] = combo.get_active_id()
        self.dark_item.handler_block_by_func(self.toggle_dark)
        self.dark_item.set_active(self.settings['theme'] == 'dark')
        self.dark_item.handler_unblock_by_func(self.toggle_dark)
        self.apply_theme()
        self.persist(update=False)

    def reset_pointer(self, dialog):
        for key in (*RANGES, 'invert_x', 'invert_y', 'roll_compensation'):
            self.settings[key] = DEFAULTS[key]
        self.persist()
        dialog.destroy()
        self.preferences()

    def controls(self):
        self.message('Button guide', '\n'.join(f'{button}: {ACTIONS[action]}' for button, action in self.settings['mappings'].items()) +
                     '\n\nHold HOME to recalibrate. This long press is always reserved.\nCalibration measures gyro drift. No sensor bar is required.')

    def button_mappings(self):
        self.present_if_needed()
        dialog, box = self.dialog('Button mappings', 560)
        note = label('Choose an action for each button. Keep an aim and a left-click\nbutton. HOME long press always recalibrates; only its tap is editable.', 'muted')
        note.set_line_wrap(True)
        box.add(note)
        grid = Gtk.Grid(column_spacing=20, row_spacing=12, margin=8)
        selectors = {}
        for i, (button, action) in enumerate(self.settings['mappings'].items()):
            grid.attach(label(button if button != 'HOME' else 'HOME (tap)'), 0, i, 1, 1)
            combo = Gtk.ComboBoxText()
            combo.get_accessible().set_name(f'{button} mapping')
            for key, title in ACTIONS.items():
                if button != 'HOME' or key != 'aim':
                    combo.append(key, title)
            combo.set_active_id(action)
            selectors[button] = combo
            grid.attach(combo, 1, i, 1, 1)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(360)
        scroll.add(grid)
        box.add(scroll)
        result = label('', 'muted')
        result.set_line_wrap(True)
        box.add(result)
        row = Gtk.Box(spacing=12)
        reset = Gtk.Button(label='Restore default mappings')
        reset.connect('clicked', lambda *_: [combo.set_active_id(DEFAULT_MAPPINGS[key]) for key, combo in selectors.items()])
        row.add(reset)
        apply = Gtk.Button(label='Apply mappings')
        apply.get_style_context().add_class('suggested-action')
        def save(*_):
            candidate = {**self.settings, 'mappings': {key: combo.get_active_id() for key, combo in selectors.items()}}
            try:
                validate(candidate)
            except ValueError as exc:
                result.set_text(str(exc))
                return
            self.settings = candidate
            self.persist()
            result.set_text('Mappings applied. Calibration is unchanged.')
        apply.connect('clicked', save)
        row.add(apply)
        box.add(row)
        dialog.show_all()

    def diagnostics(self):
        self.present_if_needed()
        dialog, box = self.dialog('Connection details', 720)
        box.add(label('Configured remote · ' + self.settings['remote_mac'], 'channel-title'))
        status = label(self.backend.message, 'muted')
        status.set_line_wrap(True)
        box.add(status)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 300)
        view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll.add(view)
        box.add(scroll)
        def update():
            status.set_text(self.backend.message)
            view.get_buffer().set_text('\n'.join(self.backend.logs) or 'Waiting for backend activity…')
            return True
        source = GLib.timeout_add(1000, update)
        dialog.connect('destroy', lambda *_: GLib.source_remove(source))
        update()
        dialog.show_all()

    def refresh(self):
        self.backend.tick()
        state = self.backend.state
        titles = dict(waiting='Waiting for remote', ready='Ready to point', calibrating='Calibrating',
                      paused='Input paused', stopping='Stopping input', error='Needs attention')
        title = titles[state]
        self.tray_status.set_label('WiiPointer · ' + title)
        self.pause_item.set_label('Resume controller input' if state in ('paused', 'error') else 'Pause controller input')
        self.pause_item.set_sensitive(state != 'stopping')
        if self.window:
            self.status_label.set_text(('●  ' if state == 'ready' else '○  ') + title)
            self.detail_label.set_text(self.backend.message)
            self.connect_button.set_sensitive(state != 'stopping')
            self.clock.set_text(datetime.now().strftime('%H:%M'))
            self.date.set_text(datetime.now().strftime('%A, %d %B'))
        return not self.quitting

    def quit_app(self, *_):
        self.quitting = True
        if self.apply_source:
            GLib.source_remove(self.apply_source)
            self.apply_source = None
        self.backend.close()
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
        self.quit()
        return False

    def do_shutdown(self):
        if self.connection_window:
            self.connection_window.destroy()
        self.backend.close()
        Gtk.Application.do_shutdown(self)


if __name__ == '__main__':
    raise SystemExit(WiiPointer().run(sys.argv))
