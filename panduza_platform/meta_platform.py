import sys
import json
import pkgutil
import argparse
import threading
import importlib
from loguru import logger
from sys import platform


from .broker import Broker
from .std_interfaces import PZA_DRIVERS_LIST as COMMON_META_DRIVERS


class MetaPlatform:
    """ Main class to manage the platform
    """

    ###########################################################################
    ###########################################################################

    def __init__(self):
        """ Constructor
        """

        # Threads
        self.threads = []

        # Drivers
        self.drivers = []
    
        # Interfaces
        self.interfaces = []
        
        #
        self.force_log = False

    ###########################################################################
    ###########################################################################

    def __parse_args(self):
        """
        """
        # Manage arguments
        parser = argparse.ArgumentParser(description='Manage Panduza Platform')
        parser.add_argument('-t', '--tree', help='path to the panduza tree (*.json)', metavar="FILE")
        parser.add_argument('-l', '--log', dest='enable_logs', action='store_true', help='start the logs')
        args = parser.parse_args()

        # Check if logs are enabled
        if not args.enable_logs and self.force_log != True:
            logger.remove()

        # Check tree filepath value
        tree_filepath = args.tree
        if not args.tree:            
            # Set the default tree path on linux
            if platform == "linux" or platform == "linux2":
                tree_filepath = "/etc/panduza/tree.json"

        # Load tree
        self.tree = {}
        with open(tree_filepath) as tree_file:
            self.tree = json.load(tree_file)


    ###########################################################################
    ###########################################################################

    def __load_tree_broker(self, machine, broker_name, broker_tree):
        """ Load interfaces declared in the tree for the given broker
        """
        # Debug log
        logger.info(" + {} ({}:{})", broker_name, broker_tree["addr"], broker_tree["port"])

        # Create broker object
        broker = Broker(broker_tree["addr"], broker_tree["port"])

        # For each interface create it
        for interface in broker_tree["interfaces"]:
            self.__interpret_interface_declaration(machine, broker, interface)

        # At last start a platform driver for this broker
        self.__load_interface(machine, broker, { "name": "platform", "driver": "platform_py" })

    ###########################################################################
    ###########################################################################

    def __replace_r_with_param(self, element, param):
        """
        """
        # If the element is a dict, replace on each value (not in the keys)
        if isinstance(element, dict):
            new_dict = {}
            for key in element:
                new_dict[key] = self.__replace_r_with_param(element[key], param)
            return new_dict

        # If the element is a string, replace %r with param
        elif isinstance(element, str):
            return element.replace("%r", str(param))


        # TODO
        # if element is arry

    ###########################################################################
    ###########################################################################

    def __interpret_interface_declaration(self, machine, broker, interface_declaration):
        """ Interpret option in the interface declaration

        Options are
        - disable: to prevent this interface from beeing loaded
        - repeated: to execute the interface loading multiple times
        """
        # Check if the interface is disabled by the user
        if "disable" in interface_declaration and interface_declaration["disable"] == True:
            name = "?"
            if "name" in interface_declaration:
                name = interface_declaration["name"]
            driver_name = "?"
            if "driver" in interface_declaration:
                driver_name = interface_declaration["driver"]
            logger.warning("> {} [{}] interface disabled", name, driver_name)
            return

        # Multiple interfaces, need to create one interface for each
        if "repeated" in interface_declaration:
            for param in interface_declaration["repeated"]:
                formated_interface_info = self.__replace_r_with_param(interface_declaration, param)
                self.__load_interface(machine, broker, formated_interface_info)

        # Only one interface to start
        else:
            self.__load_interface(machine, broker, interface_declaration)

    ###########################################################################
    ###########################################################################

    def __load_interface(self, machine, broker, interface_info):
        """
        """
        name = interface_info["name"]
        driver_name = interface_info["driver"]

        try:
            driver_obj = self.__get_compatible_driver(driver_name)

            instance = driver_obj()
            instance.initialize(self, machine, broker, interface_info)
            self.interfaces.append({
                "name": name,
                "instance":instance
            })

            logger.info("> {} [{}]", name, driver_name)
        except Exception as e:
            logger.error("{} : {} ({})", driver_name, name, str(e))

    ###########################################################################
    ###########################################################################

    def __get_compatible_driver(self, driver_name):
        """
        """
        #
        for drv in self.drivers:
            if drv().config()["compatible"] == driver_name:
                return drv
        raise Exception("driver not found")

    ###########################################################################
    ###########################################################################

    def register_driver_plugin_discovery(self):
        """
        """
        #
        logger.debug("Start plugin discovery")
        discovered_plugins = {
            name: importlib.import_module(name)
            for finder, name, ispkg
            in pkgutil.iter_modules()
            if name.startswith("panduza_drv")
        }
        logger.debug("Discovered plugins: {}", str(discovered_plugins))

        #
        for plugin_name in discovered_plugins :

            logger.info("Load plugin: '{}'", plugin_name)

            plugin_package = __import__(plugin_name)

            for drv in plugin_package.PZA_DRIVERS_LIST:
                self.register_driver(drv)

        #
        for drv in COMMON_META_DRIVERS:
            self.register_driver(drv)


    ###########################################################################
    ###########################################################################

    def get_interface_instance_from_name(self, name):
        """
        """
        for interface in self.interfaces:
            if interface["name"] == name:
                return interface["instance"]
        raise Exception("interface not found")

    ###########################################################################
    ###########################################################################

    def register_driver(self, driver):
        """
        """
        logger.info("Register driver: '{}'", driver().config()["compatible"])
        self.drivers.append(driver)

    ###########################################################################
    ###########################################################################

    def run(self):
        """Run the platform
        """

        try:
            # Manage args
            self.__parse_args()

            # Parse configs
            logger.debug("load tree:{}", json.dumps(self.tree, indent=1))
            for broker in self.tree["brokers"]:
                self.__load_tree_broker(self.tree["machine"], broker, self.tree["brokers"][broker])

            # Setup all the interfaces in the same thread
            for interface in self.interfaces:
                interface["instance"].initial_setup()

            # Run all the interfaces on differents threads
            for interface in self.interfaces:
                t = threading.Thread(target=interface["instance"].start)
                self.threads.append(t)

            # Start all the threads
            for thread in self.threads:
                thread.start()
            
            # Log
            logger.info("Platform started !")

            # Join them all !
            for thread in self.threads:
                thread.join()

        except KeyboardInterrupt:
            logger.warning("ctrl+c => user stop requested")
            self.stop()

    ###########################################################################
    ###########################################################################

    def stop(self):
        """
        To stop the platform
        """
        # Request a stop for each driver
        for interface in self.interfaces:
            interface["instance"].stop()

        # Join them all !
        for thread in self.threads:
            thread.join()
