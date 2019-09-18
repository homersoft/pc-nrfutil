import binascii
import functools
import logging
import threading
import time
from uuid import UUID

import dbus
import dbus.types
import dbus.mainloop.glib
from gi.repository import GLib
from dbus.exceptions import DBusException

from pc_ble_driver_py.ble_driver import BLEUUID, BLEUUIDBase, BLEGapAddr, BLEAdvData, BLEGattStatusCode, BLEHci, \
                                        BLEGapRoles, NordicSemiErrorCheck
from pc_ble_driver_py.exceptions import NordicSemiException
from pc_ble_driver_py.observers import BLEAdapterObserver, BLEDriverObserver

logger = logging.getLogger(__name__)


DBUS_OBJECT_MANAGER_IF = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IF = "org.freedesktop.DBus.Properties"

GATT_CHARACTERISTIC_IF = "org.bluez.GattCharacteristic1"

BLUEZ_ADAPTER_IF = "org.bluez.Adapter1"
BLUEZ_DEV_IF = "org.bluez.Device1"


def uuid_to_ble_uuid(uuid):
    """ Function converts UUID to BLEUUID.

    :param uuid: uuid.UUID
    :return: BLEUUID
    """
    uuid = UUID(uuid)

    uuid_bytes = bytearray(uuid.bytes)
    value = uuid_bytes[2] << 8 | uuid_bytes[3]

    uuid_bytes[2] = 0x00
    uuid_bytes[3] = 0x00

    return BLEUUID(value, BLEUUIDBase(list(uuid_bytes)))


def ble_uuid_to_uuid(ble_uuid):
    """ Function converts BLEUUID to UUID.

    :param ble_uuid: BLEUUID
    :return: uuid.UUID
    """
    uuid_bytes = bytearray(ble_uuid.base.base)

    uuid_bytes[2] = (ble_uuid.value >> 8) & 0xFF
    uuid_bytes[3] = (ble_uuid.value) & 0xFF

    return UUID(bytes=bytes(uuid_bytes))


def get_bluez_objects(bus):
    """ Function gets all DBUS objects from org.bluez.

    :param bus: path to bus.
    :return: dbus.Dictionary<dbus.String, dbus.Dictionary>, paths to objects
    """
    obj = bus.get_object("org.bluez", "/")
    obj_mgr_if = dbus.Interface(obj, DBUS_OBJECT_MANAGER_IF)

    return obj_mgr_if.GetManagedObjects()


def contains_interfaces_with_name(interfaces, name):
    """ Function checks if interfaces contains interface with name.

    :param interfaces: dbus.Dictionary<dbus.String, dbus.Dictionary>, interfaces
    :param name: str, interface name
    :return: bool
    """
    return any([interface_name for interface_name in interfaces.keys() if interface_name == name])


def find_ble_adapters(objects):
    """ Function finds all bluetooth adapter compatible with BlueZ.

    :param objects: dbus.Dictionary<dbus.String, dbus.Dictionary>
    :return: list<dbus.String>, list of DBUS paths to adapters.
    """
    return [path for path, interfaces in objects.items() if contains_interfaces_with_name(interfaces, BLUEZ_ADAPTER_IF)]


def find_ble_devices(objects):
    """ Function finds all devices detected by an adapter.

    :param objects: dbus.Dictionary<dbus.String, dbus.Dictionary>
    :return: list<dbus.String>, list of DBUS paths to adapters.
    """
    return [path for path, interfaces in objects.items() if contains_interfaces_with_name(interfaces, BLUEZ_DEV_IF)]


class BleGattCharacteristic(object):
    """ Wrapper that simplify DBUS characteristic API. """

    def __init__(self, bus, char_path):
        self._bus = bus
        self._if = GATT_CHARACTERISTIC_IF
        self._char_path = char_path
        self._dbus_obj = bus.get_object("org.bluez", char_path)
        self._dbus_if = dbus.Interface(self._dbus_obj, self._if)
        self._dbus_prop_if = dbus.Interface(self._dbus_obj, DBUS_PROPERTIES_IF)

        self._notification_handlers = []

    def add_notification_handler(self, handler):
        """ Add notification handler.

            :param handler: Callable, handler to be called when notification received.
        """
        self._notification_handlers.append(handler)

    def write(self, data, with_response=False):
        """ Write data to characteristic.

        :param data: bytearray, data to be written
        :param with_response: bool, data will be written to characteristic with acknowledge (handled by bluez)
        """
        options = dbus.types.Dictionary()
        options["type"] = "request" if with_response else "command"

        self._dbus_if.WriteValue(data, options)

    def notification_handler(self, interface_name, changed_properties, _):
        if interface_name != GATT_CHARACTERISTIC_IF:
            return

        for property_name, new_value in changed_properties.items():
            if property_name != "Value":
                continue

            for handler in self._notification_handlers:
                handler(self, bytearray(new_value))

    def start_notify(self):
        """ Enable notifications. """
        self._dbus_prop_if.connect_to_signal("PropertiesChanged", self.notification_handler)
        self._dbus_if.StartNotify()

    def stop_notify(self):
        """ Disable notifications. """
        self._dbus_if.StopNotify()

    @property
    def uuid(self):
        return self._dbus_prop_if.Get(self._if, "UUID")

    @property
    def flags(self):
        return self._dbus_prop_if.Get(self._if, "Flags")

    def __repr__(self):
        return "{}: {}".format(self._char_path, self.uuid)


class BleDevice(object):
    """ Wrapper that simplify DBUS device API. """

    DEFAULT_RSSI = -100
    DEFAULT_NAME = "N/A"

    def __init__(self, bus, device_path):
        self._bus = bus
        self._if = BLUEZ_DEV_IF
        self._device_path = device_path
        self._dbus_obj = bus.get_object("org.bluez", device_path)
        self._dbus_if = dbus.Interface(self._dbus_obj, self._if)
        self._dbus_prop_if = dbus.Interface(self._dbus_obj, DBUS_PROPERTIES_IF)

        self._characteristics = []

    def connect(self):
        """ Connect to device. """
        try:
            self._dbus_if.Connect()
            return True

        except DBusException as err:
            logger.error("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return False

    def disconnect(self):
        """ Disconnect from device. """
        try:
            self._dbus_if.Disconnect()
            return True

        except DBusException as err:
            logger.error("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return False

    def discover_services(self):
        """ Perform service discovery procedure. """

        timeout = 10
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.services_resolved:
                break
        else:
            raise RuntimeError("Could not discover services.")

        for path, interfaces in get_bluez_objects(self._bus).items():
            if not self._device_path in path:
                continue

            for interface in interfaces.keys():

                if interface == GATT_CHARACTERISTIC_IF:
                    self._characteristics.append(BleGattCharacteristic(self._bus, path))

    @property
    def characteristics(self):
        return self._characteristics

    @property
    def address(self):
        return self._dbus_prop_if.Get(self._if, "Address")

    @property
    def rssi(self):
        try:
            return int(self._dbus_prop_if.Get(self._if, "RSSI"))

        except DBusException as err:
            logger.warning("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return self.DEFAULT_RSSI

    @property
    def name(self):
        try:
            return self._dbus_prop_if.Get(self._if, "Name")

        except DBusException as err:
            logger.warning("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return self.DEFAULT_NAME

    @property
    def device_path(self):
        return self._device_path

    @property
    def services_resolved(self):
        return bool(self._dbus_prop_if.Get(self._if, "ServicesResolved"))

    def __repr__(self):
        return "{} [{}]".format(self.name, self.address)


class BleAdapter(object):
    """ Wrapper that simplify DBUS adapter API. """

    def __init__(self, bus, adapter_path):
        """
        :param name: str, e.g. hci0
        """
        self._bus = bus
        self._adapter_path = adapter_path
        self._dbus_obj = bus.get_object("org.bluez", adapter_path)
        self._dbus_if = dbus.Interface(self._dbus_obj, BLUEZ_ADAPTER_IF)
        self._dbus_prop_if = dbus.Interface(self._dbus_obj, DBUS_PROPERTIES_IF)

    def remove_device(self, device_path):
        """ Remove device object.

        :param device_path: str, path to the device to be removed.
        """
        try:
            self._dbus_if.RemoveDevice(device_path)
        except Exception:
            pass


    def clear_last_discovery_results(self):
        """ Clear last discovery result. """
        for dev in self.devices():
            dev.disconnect()
            self.remove_device(dev.device_path)

    def start_discovery(self):
        """ Start discovery procedure.

        :return: bool, True when startted, False otherwise
        """
        self.clear_last_discovery_results()

        try:
            self._dbus_if.StartDiscovery()
            return True

        except DBusException as err:
            logger.error("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return False

    def stop_discovery(self):
        """ Stop discovery procedure.

        :return: bool, True when stopped, False otherwise
        """
        try:
            self._dbus_if.StopDiscovery()
            return True

        except DBusException as err:
            logger.error("%s: %s", err.get_dbus_name(), err.get_dbus_message())
            return False

    def devices(self):
        """ Return found devices.

        :return: list<BleDevice>, list of BLE devices.
        """
        all_devices = [BleDevice(self._bus, dev_path) for dev_path in find_ble_devices(get_bluez_objects(self._bus))]
        return [dev for dev in all_devices if self._adapter_path in dev.device_path]

    @classmethod
    def first_adapter(cls):
        """ Create adapter instance with first found BLE adapter.

        :return: cls, adapter instance
        """
        bus = dbus.SystemBus()

        available_adapters = find_ble_adapters(get_bluez_objects(bus))

        if not len(available_adapters):
            raise ValueError("Could not find any Bluetooth adapter.")

        return cls(bus, available_adapters[0])


class BluezConnection(object):
    """ Class keeps information related to connection. """

    def __init__(self, conn_handle, device):
        self.conn_handle = conn_handle
        self.device = device

    def discover_services(self):
        """ Perform service discovery procedure. """
        self.device.discover_services()

    def get_char_handle(self, uuid):
        """ Get characteristic.

        :param uuid: BLEUUID, characteristic UUID

        :return: BleCharacteristic or None
        """
        for char in self.device.characteristics:
            if str(char.uuid) == str(ble_uuid_to_uuid(uuid)):
                return char

    def get_cccd_handle(self, uuid):
        """ Get CCCD. This is dummy method always return None.
        This method is not implemented because buttonless bootloader is not supported in firmware.

        :return: None
        """
        return None


class BluezConnectionManager(object):
    """ Class keeps information about connections. """

    def __init__(self):
        # Current implmentation handle only one connection.
        self._conn_handle = 1
        self._db_conn = {}

    def __get_next_conn_handle(self):
        return self._conn_handle

    def create_new_connection(self, device):
        conn_handle = self.__get_next_conn_handle()
        self._db_conn[conn_handle] = BluezConnection(conn_handle,device)

        return conn_handle

    def get_connection(self, conn_handle):
        return self._db_conn[conn_handle]


class BluezDriver(object):
    """ Class is responsible for calling low level operations on BlueZ stack. """

    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        self._ble_adapter = BleAdapter.first_adapter()

        self._scanning_in_progress_evt = threading.Event()
        self._scanning_in_progress_evt.clear()

        self._main_loop_thread = None
        self._scanner_thread = None

        self.observers = list()
        self.devices   = dict()

        self.conn_manager = BluezConnectionManager()

    def __main_loop(self):
        """ Thread with main loop.
        This main loop is required by dbus python library to be able to receive DBUS signals. It just run in loop.
        """
        loop = GLib.MainLoop()
        loop.run()

    def __device_scanner(self):
        """ Thread with device scanner."""
        self._scanning_in_progress_evt.set()

        while self._scanning_in_progress_evt.is_set():
            self.devices = {dev.address.replace(":", "").lower(): dev for dev in self._ble_adapter.devices()}

            for _, dev in self.devices.items():
                addr_type = BLEGapAddr.Types.public
                addr = bytearray(binascii.unhexlify(dev.address.replace(":", "")))

                peer_addr = BLEGapAddr(addr_type, addr)
                rssi = dev.rssi

                adv_type = None
                adv_data = BLEAdvData()

                for obs in self.observers:
                    obs.on_gap_evt_adv_report(self, None, peer_addr, rssi, adv_type, adv_data)

                if not self._scanning_in_progress_evt.is_set():
                    return

            time.sleep(0.2)

    def observer_register(self, observer):
        """ Register observer.

        :param observer: BLEDriverObserver
        """
        self.observers.append(observer)

    def observer_unregister(self, observer):
        """ Unregister observer.

        :param observer: BLEDriverObserver
        """
        self.observers.remove(observer)

    def open(self):
        """ Open driver."""
        self.__start_main_thread()

    def close(self):
        """ Close driver. """
        self.__stop_scanner_thread()
        self.__stop_main_thread()

    def ble_enable(self, ble_enable_params):
        # This is just dummy method required by nrfutil API
        pass

    def ble_vs_uuid_add(self, uuid):
        # This is just dummy method required by nrfutil API
        pass

    def ble_gap_scan_start(self):
        """ Start scanning for devices. """
        self._ble_adapter.start_discovery()
        self.__start_scanner_thread()

    def ble_gap_scan_stop(self):
        """ Stop scanning for devices. """
        self.__stop_scanner_thread()
        self._ble_adapter.stop_discovery()

    def ble_gap_connect(self, address, scan_params, conn_params):
        """ Connect to device.
        It also notifies registered observers when connection is successful.

        :param address: BLEGapAddr, device address
        :param scan_params: None, scan parameters 
        :param conn_params: BLEGapConnParams, connection parameters
        """
        self._scanning_in_progress_evt.clear()

        dev = self.devices[binascii.hexlify(address.addr)]
        if dev is None:
            raise RuntimeError("Could not find device with address")

        if not dev.connect():
            raise RuntimeError("Could not connect to device: {}".format(binascii.hexlify(address.addr)))

        conn_handle = self.conn_manager.create_new_connection(dev)

        for obs in self.observers:
            obs.on_gap_evt_connected(ble_driver = self,
                                     conn_handle = conn_handle,
                                     peer_addr = address,
                                     role = BLEGapRoles.periph,
                                     conn_params = conn_params)

    def ble_gap_disconnect(self, conn_handle):
        """ Disconnect from device.

        :param conn_handle:, int, connection handle.
        """
        conn = self.conn_manager.get_connection(conn_handle)
        if conn is None:
            logger.info("Could not disconnect. Connection does not exist.")
            return

        conn.device.disconnect()

        for obs in self.observers:
            obs.on_gap_evt_disconnected(self, conn_handle, BLEHci.success)

    def get_connection(self, conn_handle):
        """ Get connection by connection handle.

        :param conn_handle: int, connection handle
        """
        return self.conn_manager.get_connection(conn_handle)

    def __start_scanner_thread(self):
        """ Start scanner thread. """
        if self._scanner_thread is not None:
            raise ValueError("Could not start thread. Looks like other scanner thread has not been finished.")

        self._scanner_thread = threading.Thread(target=self.__device_scanner)
        self._scanner_thread.daemon = True
        self._scanner_thread.start()

    def __stop_scanner_thread(self):
        """ Stop scanner thread. """
        if self._scanner_thread is None:
            return

        if not self._scanner_thread.is_alive():
            self._scanner_thread = None
            return

        self._scanning_in_progress_evt.clear()

        self._scanner_thread.join(timeout=5)
        self._scanner_thread = None

    def __start_main_thread(self):
        """ Start main thread. """
        if self._main_loop_thread is not None:
            raise ValueError("Could not start thread. Main loop thread has been already started.")

        self._main_loop_thread = threading.Thread(target=self.__main_loop)
        self._main_loop_thread.daemon = True
        self._main_loop_thread.start()

    def __stop_main_thread(self):
        """ Stop main thread. """
        if self._main_loop_thread is None:
            return

        if not self._main_loop_thread.is_alive():
            self._main_loop_thread = None
            return

        self._main_loop_thread = None


class BluezBleAdapter(object):
    """ Class responsible for interfaction with nrf-util. It is kind of adapter for BluezDriver. """

    DEFAULT_ATT_MTU = 23

    def __init__(self):
        self.conn_in_progress = False
        self.db_conns = dict()
        self.observers = list()

        self.driver = BluezDriver()

    def observer_register(self, observer):
        """ Register observer.

        :param observer: BLEAdapterObserver, observer
        """
        self.observers.append(observer)

    def observer_unregister(self, observer):
        """ Unregister observer.

        :param observer: BLEAdapterObserver, observer
        """
        self.observers.remove(observer)

    def open(self):
        """ Open adapter. """
        self.driver.open()

        self.conn_in_progress = False
        self.db_conns = dict()

    def close(self):
        """ Close adapter. """
        self.driver.close()

        self.conn_in_progress = False
        self.db_conns = dict()

    def connect(self, address, scan_params=None, conn_params=None):
        """Connect to device.

        :param address: BLEGapAddr, device address
        :param scan_params: None, scan params
        :param conn_params: BLEGapConnParams, conn params
        """
        if self.conn_in_progress:
            return

        self.conn_in_progress = True
        self.driver.ble_gap_connect(address = address,
                                    scan_params = scan_params,
                                    conn_params = conn_params)

    def disconnect(self, conn_handle):
        """ Disconnect from device.

        :param conn_handle: int, connection handle
        """
        self.driver.ble_gap_disconnect(conn_handle)

    def att_mtu_exchange(self, conn_handle):
        """ Set ATT MTU.
        Current implementation does not support change of ATT MTU.

        :param conn_handle: int, connection handle
        :return: int, ATT MTU
        """
        # Currently changing ATT MTU is not possible.
        self.db_conns[conn_handle].att_mtu = self.DEFAULT_ATT_MTU
        return self.db_conns[conn_handle].att_mtu

    @NordicSemiErrorCheck(expected = BLEGattStatusCode.success)
    def service_discovery(self, conn_handle, uuid=None):
        """ Perform service discovery.

        :param conn_handle: int, connection handle
        :param uuid: BLEUUID, uuid
        :return: BLEGattStatusCode, return code
        """
        self.db_conns[conn_handle] = self._get_conn_by_conn_handle(conn_handle)
        self.db_conns[conn_handle].discover_services()

        return BLEGattStatusCode.success

    def _get_conn_by_conn_handle(self, conn_handle):
        """ Get connection.

        :param conn_handle: int, connection handle
        :return: BluezConnection
        """
        conn = self.driver.get_connection(conn_handle)

        if conn is not None:
            return conn

        raise ValueError("Could not get connection with conn_handle: {}".format(conn_handle))

    def _get_characteristic_with_uuid(self, conn, uuid):
        """ Get characteristic with UUID.

        :param conn: BluezConnection, connection
        :param uuid: BLEUUID, uuid
        :return: BleCharacteristic
        """
        char = conn.get_char_handle(uuid)

        if char is not None:
            return char

        raise ValueError("Could not get characteristic with UUID: {}".format(str(uuid)))

    def _on_notification_handler(self, char, data, conn_handle):
        """ Handler called on characteristic notification.

        :param char: BleCharacteristic, characteristic
        :param data: bytearray, received data
        :param conn_handle: int, connection handle
        """
        for obs in self.observers:
            obs.on_notification(self, conn_handle, uuid_to_ble_uuid(char.uuid), data)

    @NordicSemiErrorCheck(expected=BLEGattStatusCode.success)
    def enable_notification(self, conn_handle, uuid):
        """ Enable notifications for characteristic with UUID.

        :param conn_handle: int, connection handle
        :param uuid: BLEUUID, uuid
        :return: BLEGattStatusCode
        """
        char = self._get_characteristic_with_uuid(self._get_conn_by_conn_handle(conn_handle), uuid)

        char.add_notification_handler(functools.partial(self._on_notification_handler, conn_handle=conn_handle))
        char.start_notify()

        return BLEGattStatusCode.success

    @NordicSemiErrorCheck(expected=BLEGattStatusCode.success)
    def disable_notification(self, conn_handle, uuid):
        """ Disable  notifications for characteristic with UUID.

        :param conn_handle: int, connection handle
        :param uuid: BLEUUID, uuid
        :return: BLEGattStatusCode
        """
        char = self._get_characteristic_with_uuid(self._get_conn_by_conn_handle(conn_handle), uuid)
        char.stop_notify()

        return BLEGattStatusCode.success

    @NordicSemiErrorCheck(expected=BLEGattStatusCode.success)
    def write_req(self, conn_handle, uuid, data):
        """ Write request to characteristic.

        :param conn_handle: int, connection handle
        :param uuid: BLEUUID, uuid
        :param data: list<int>, data to be written
        :return: BLEGattStatusCode
        """
        char = self._get_characteristic_with_uuid(self._get_conn_by_conn_handle(conn_handle), uuid)
        char.write(data, with_response=True)

        return BLEGattStatusCode.success

    @NordicSemiErrorCheck(expected=BLEGattStatusCode.success)
    def write_cmd(self, conn_handle, uuid, data):
        """ Write command to characteristic.

        :param conn_handle: int, connection handle
        :param uuid: BLEUUID, uuid
        :param data: list<int>, data to be written
        :return: BLEGattStatusCode
        """
        char = self._get_characteristic_with_uuid(self._get_conn_by_conn_handle(conn_handle), uuid)
        char.write(data, with_response=False)

        return BLEGattStatusCode.success

    def on_gap_evt_connected(self, ble_driver, conn_handle, peer_addr, role, conn_params):
        self.conn_in_progress = False

    def on_gap_evt_disconnected(self, ble_driver, conn_handle, reason):
        del self.db_conns[conn_handle]
