import unittest
from unittest.mock import Mock
from bluetooth_helper import ConnectionHelper, connection_info

MAC = '00:11:22:33:44:55'


class ConnectionTests(unittest.TestCase):
    def objects(self, powered=True, paired=True, connected=False):
        return {'/org/bluez/hci0': {'org.bluez.Adapter1': {'Powered': powered}},
                '/org/bluez/hci0/dev_remote': {'org.bluez.Device1': {
                    'Alias': 'Nintendo RVL-CNT-01', 'Address': MAC, 'Adapter': '/org/bluez/hci0',
                    'Paired': paired, 'Connected': connected}}}

    def test_helper_explains_missing_off_unpaired_disconnected_and_connected_states(self):
        for objects, phrase in (({}, 'No Bluetooth adapter'),
                                (self.objects(powered=False), 'Bluetooth is off'),
                                (self.objects(paired=False), 'not paired'),
                                (self.objects(), 'Press A'),
                                (self.objects(connected=True), 'Bluetooth connected')):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, connection_info(objects, MAC)['message'])

    def test_selected_remote_uses_its_own_adapter(self):
        objects = self.objects()
        objects['/org/bluez/hci1'] = {'org.bluez.Adapter1': {'Powered': True}}
        objects['/org/bluez/hci0/dev_remote']['org.bluez.Device1']['Adapter'] = '/org/bluez/hci1'
        info = connection_info(objects, MAC.lower())
        self.assertEqual(info['adapter'][0], '/org/bluez/hci1')
        self.assertEqual(info['remotes'], [(MAC, 'Nintendo RVL-CNT-01')])

    def test_power_and_connect_call_bluez_without_a_shell(self):
        helper = ConnectionHelper()
        helper.info = connection_info(self.objects(), MAC)
        helper.call = Mock()
        callback = Mock()
        helper.power_on(callback)
        self.assertEqual(helper.call.call_args.args[2], 'Set')
        self.assertEqual(helper.call.call_args.args[3].unpack(), ('org.bluez.Adapter1', 'Powered', True))
        helper.connect_remote(callback)
        self.assertEqual(helper.call.call_args.args[:3], ('/org/bluez/hci0/dev_remote', 'org.bluez.Device1', 'Connect'))

    def test_unpaired_remote_gets_pairing_instructions(self):
        helper = ConnectionHelper()
        helper.info = connection_info(self.objects(paired=False), MAC)
        helper.call = Mock()
        callback = Mock()
        helper.connect_remote(callback)
        helper.call.assert_not_called()
        self.assertIn('Pair', callback.call_args.args[1])

    def test_discovery_is_balanced_even_when_dialog_closes_during_start(self):
        helper = ConnectionHelper()
        helper.info = connection_info(self.objects(), MAC)
        helper.call = Mock()
        helper.scan(Mock())
        started = helper.call.call_args.args[-1]
        helper.close()
        started((), None)
        self.assertEqual(helper.call.call_args.args[2], 'StopDiscovery')
        self.assertIsNone(helper.scanning_adapter)

    def test_no_adapter_and_powered_off_requests_fail_safely(self):
        helper = ConnectionHelper()
        callback = Mock()
        helper.power_on(callback)
        self.assertIn('No Bluetooth adapter', callback.call_args.args[1])
        helper.info = connection_info(self.objects(powered=False), MAC)
        helper.scan(callback)
        self.assertIn('Turn Bluetooth on', callback.call_args.args[1])
