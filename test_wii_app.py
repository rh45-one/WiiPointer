"""Native UI smoke tests. Run with xvfb-run -a /usr/bin/python3 -m unittest test_wii_app."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(os.environ.get('DISPLAY'), 'Requires a display (use xvfb-run)')
class DesktopUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from wii_app import WiiPointer, Gtk, GLib
        cls.Gtk, cls.GLib = Gtk, GLib
        cls.directory = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, XDG_CONFIG_HOME=cls.directory.name):
            cls.app = WiiPointer()
        cls.app.set_application_id(f'io.github.wiipointer.Tests.p{os.getpid()}')
        cls.start = patch.object(cls.app.backend, 'start')
        cls.start.start()
        cls.app.register()
        cls.app.activate()
        cls.pump()

    @classmethod
    def tearDownClass(cls):
        cls.app.quit_app()
        cls.app.window.destroy()
        cls.start.stop()
        cls.directory.cleanup()

    @classmethod
    def pump(cls):
        while cls.Gtk.events_pending():
            cls.Gtk.main_iteration_do(False)

    def tearDown(self):
        for window in self.Gtk.Window.list_toplevels():
            if window != self.app.window and isinstance(window, self.Gtk.Dialog):
                window.destroy()
        self.pump()

    def descendants(self, widget):
        yield widget
        if isinstance(widget, self.Gtk.Container):
            for child in widget.get_children():
                yield from self.descendants(child)

    def test_channels_and_all_dialogs_open(self):
        self.app.backend.state = 'waiting'
        channels = [w for w in self.descendants(self.app.window)
                    if isinstance(w, self.Gtk.Button) and w.get_style_context().has_class('channel')]
        self.assertEqual(len(channels), 6)
        for channel in channels:
            channel.clicked()
            self.pump()
            dialogs = [w for w in self.Gtk.Window.list_toplevels() if isinstance(w, self.Gtk.Dialog)]
            self.assertTrue(dialogs, channel.get_accessible().get_name())
            for dialog in dialogs:
                dialog.destroy()

    def test_all_pointer_controls_save_and_map_to_backend(self):
        from desktop_backend import command
        self.app.preferences()
        controls = list(self.descendants(self.app.preferences_window))
        scales = [w for w in controls if isinstance(w, self.Gtk.Scale)]
        switches = [w for w in controls if isinstance(w, self.Gtk.Switch)]
        self.assertEqual((len(scales), len(switches)), (4, 3))
        for scale, value in zip(scales, (19, 40, .7, .6)):
            scale.set_value(value)
        for switch in switches:
            switch.set_active(not switch.get_active())
        self.assertEqual(self.app.settings['sensitivity'], 19)
        self.assertAlmostEqual(self.app.settings['smoothing'], .04)
        self.assertEqual(self.app.settings['deadzone'], .7)
        self.assertAlmostEqual(self.app.settings['acceleration'], .6)
        args = command(self.app.settings)
        for flag in ('--no-invert-x', '--invert-y', '--no-roll-compensation'):
            self.assertIn(flag, args)
        self.assertTrue(self.app.settings_path.exists())
        self.app.reset_pointer(self.app.preferences_window)
        self.assertEqual(self.app.settings['sensitivity'], 12)

    def test_pointer_changes_use_live_update_even_while_paused(self):
        for state in ('ready', 'paused', 'calibrating', 'waiting'):
            self.app.backend.state = state
            with patch.object(self.app.backend, 'update') as update, \
                 patch.object(self.app.backend, 'start') as start:
                self.app.persist()
                if self.app.apply_source:
                    self.GLib.source_remove(self.app.apply_source)
                self.app.apply_settings()
                update.assert_called_once_with(self.app.settings)
                start.assert_not_called()

    def test_footer_says_hide_to_tray(self):
        buttons = [w.get_label() for w in self.descendants(self.app.window) if isinstance(w, self.Gtk.Button)]
        self.assertIn('Hide to tray', buttons)
        self.assertNotIn('Wii  ⌄', buttons)

    def test_mapping_editor_saves_changes_and_rejects_missing_aim(self):
        self.app.button_mappings()
        dialog = next(w for w in self.Gtk.Window.list_toplevels() if w.get_title() == 'Button mappings')
        widgets = list(self.descendants(dialog))
        combos = {w.get_accessible().get_name(): w for w in widgets if isinstance(w, self.Gtk.ComboBoxText)}
        self.assertEqual(len(combos), 11)
        apply = next(w for w in widgets if isinstance(w, self.Gtk.Button) and w.get_label() == 'Apply mappings')
        combos['A mapping'].set_active_id('aim')
        combos['B mapping'].set_active_id('left_click')
        apply.clicked()
        self.assertEqual(self.app.settings['mappings']['A'], 'aim')
        self.assertEqual(self.app.settings['mappings']['B'], 'left_click')
        combos['A mapping'].set_active_id('none')
        apply.clicked()
        self.assertEqual(self.app.settings['mappings']['A'], 'aim')
        reset = next(w for w in widgets if isinstance(w, self.Gtk.Button) and w.get_label() == 'Restore default mappings')
        reset.clicked()
        apply.clicked()
        self.assertEqual(self.app.settings['mappings']['B'], 'aim')

    def test_connection_helper_actions_and_address_validation(self):
        from bluetooth_helper import connection_info
        with patch('wii_app.ConnectionHelper') as constructor:
            helper = constructor.return_value
            helper.closed = False
            helper.refresh.side_effect = lambda address, callback: callback(connection_info({}, address), None)
            self.app.connection()
            dialog = self.app.connection_window
            widgets = list(self.descendants(dialog))
            buttons = {w.get_label(): w for w in widgets if isinstance(w, self.Gtk.Button)}
            for title, method in (('Turn Bluetooth on', helper.power_on), ('Scan for remotes', helper.scan),
                                  ('Connect', helper.connect_remote)):
                buttons[title].clicked()
                method.assert_called_once()
            address = next(w for w in widgets if isinstance(w, self.Gtk.Entry))
            address.set_text('not a Bluetooth address')
            old = self.app.settings['remote_mac']
            buttons['Use this remote'].clicked()
            self.assertEqual(self.app.settings['remote_mac'], old)
            dialog.destroy()
            helper.close.assert_called_once()

    def test_light_dark_and_system_appearance(self):
        self.app.preferences('appearance')
        combo = next(w for w in self.descendants(self.app.preferences_window)
                     if isinstance(w, self.Gtk.ComboBoxText))
        for theme in ('dark', 'light', 'system'):
            combo.set_active_id(theme)
            self.assertEqual(self.app.settings['theme'], theme)
            self.assertEqual(self.app.dark_item.get_active(), theme == 'dark')
        self.app.dark_item.set_active(True)
        self.assertEqual(self.app.settings['theme'], 'dark')

    def test_pause_resume_does_not_restart_or_calibrate(self):
        self.app.backend.state = 'ready'
        self.app.backend.message = 'Ready for UI test'
        self.app.refresh()
        with patch.object(self.app.backend, 'pause') as pause:
            self.app.toggle_backend()
            pause.assert_called_once()
        self.app.backend.state = 'paused'
        self.app.backend.start.reset_mock()
        self.app.toggle_backend()
        self.app.backend.start.assert_called_once_with(self.app.settings)
        self.app.backend.state = 'waiting'

    def test_tray_close_hides_but_does_not_stop_backend(self):
        real_indicator = self.app.indicator
        fake = Mock()
        fake.get_status.return_value = real_indicator.get_status()
        fake.get_property.return_value = True
        with patch.object(self.app, 'indicator', fake), patch.object(self.app.backend, 'stop') as stop:
            self.app.close_window()
            self.assertFalse(self.app.window.get_visible())
            stop.assert_not_called()
        self.app.present_window()
        fake.get_property.return_value = False
        with patch.object(self.app, 'indicator', fake):
            self.app.close_window()
            self.assertTrue(self.app.window.get_visible())

    def test_bluetooth_launch_errors_are_visible(self):
        from wii_app import Gio, GLib
        with patch.object(Gio.Subprocess, 'new', side_effect=GLib.Error('Unavailable')), \
             patch.object(self.app, 'message') as message:
            self.app.bluetooth_settings()
            message.assert_called_once()

    def test_native_screenshots(self):
        directory = os.environ.get('WII_SCREENSHOT_DIR')
        if not directory:
            self.skipTest('Set WII_SCREENSHOT_DIR to capture both appearances')
        from wii_app import Gdk
        animation_setting = self.Gtk.Settings.get_default()
        old_animations = animation_setting.get_property('gtk-enable-animations')
        animation_setting.set_property('gtk-enable-animations', False)
        self.addCleanup(animation_setting.set_property, 'gtk-enable-animations', old_animations)
        self.app.backend.state = 'waiting'
        self.app.backend.message = 'Press A on your paired Wii Remote, then set it down.'
        self.app.refresh()
        for theme in ('light', 'dark'):
            self.app.settings['theme'] = theme
            self.app.apply_theme()
            self.app.present_window()
            self.pump()
            # Force drawing before reading the native window's pixels.
            self.app.window.queue_draw()
            self.app.window.get_window().process_updates(True)
            self.pump()
            window = self.app.window.get_window()
            image = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
            Path(directory).mkdir(parents=True, exist_ok=True)
            image.savev(str(Path(directory)/f'{theme}.png'), 'png', [], [])


if __name__ == '__main__':
    unittest.main()
