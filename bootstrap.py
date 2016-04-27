#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# Patch threading, queue _time with monotonic
from monotonic import monotonic
import threading
threading._time = monotonic
import Queue
Queue._time = monotonic

import os
import sys
import logging
import logging.config
import imp
import inspect
import json
from collections import namedtuple
from threading import Thread
from threading import Event
from time import sleep
from voluptuous import Schema, REMOVE_EXTRA, Any, All, Length

from sanji.core import Sanji
from sanji.core import Route
from sanji.model_initiator import ModelInitiator
from sanji.bundle import Bundle
from sanji.connection.mqtt import Mqtt

_logger = logging.getLogger("sanji.bootstrap")

BundleMeta = namedtuple(
    'BundleMeta', 'thread, stop_event, connection, instance')

DEFAULT_BUNDLE_BOOT_TIMEOUT = 600


class SanjiKeeper(object):

    def __init__(self, *args, **kwargs):
        self.running_bundles = {}
        self.is_booted = False

    @staticmethod
    def get_bundle_paths(dir_path):
        dirs = []
        for file in os.listdir(dir_path):
            if file == "bundle.json":
                return [dir_path]
            child_dir_path = os.path.join(dir_path, file)
            if os.path.isdir(child_dir_path):
                dirs.append(child_dir_path)

        # if this dir has no exist bundle.json file, then go deeper
        bundle_paths = []
        for child_dir_path in dirs:
            child_bundles = SanjiKeeper.get_bundle_paths(child_dir_path)
            if len(child_bundles) > 0:
                # concat two list
                bundle_paths = bundle_paths + child_bundles

        return bundle_paths

    @staticmethod
    def get_bundles(bundle_paths, omitted_bundle_names=[]):
        """
        Load all bundle.json from given bundle_paths
        Return dict() key=path, value=Bundle instance
        """
        bundles = {}
        for path in bundle_paths:
            bundle = Bundle(bundle_dir=path)
            if bundle.profile["name"] in omitted_bundle_names:
                _logger.debug(
                    "Bundle [%s] has been omitted by mode config" %
                    (bundle.profile["name"]))
                continue

            bundles[path] = bundle

        return bundles

    @staticmethod
    def get_sanji_class(class_name, pyfile):

        def predicate(member):
            return inspect.isclass(member) and \
                issubclass(member, Sanji)

        # dynamic load import module via property "main" in bundle config
        module = imp.load_source(class_name, pyfile)
        result = inspect.getmembers(module, predicate)

        for classObj in result:
            if classObj[0] == 'Sanji':
                continue
            return classObj[1]

        return None

    @staticmethod
    def sort_bundles(bundles):
        def key_func(bundlePath):
            return bundles[bundlePath].profile["priority"]

        return sorted(bundles, key=key_func)

    def boot(*args, **kwargs):
        bundle = kwargs.get("bundle")
        bundle_dir = kwargs.get("bundle_dir")
        stop_event = kwargs.get("stop_event", Event())
        connection = kwargs.get("connection", Mqtt())

        main_name, ext = os.path.splitext(bundle.profile["main"])

        if main_name == "bootstrap":
            raise RuntimeError("Ignore class: bootstrap")
        if ext != ".py":
            raise RuntimeError("Ignore none python bundle: %s" % ext)

        # Append bundle path into sys.path
        sys.path.append(bundle_dir)
        pyfile = os.path.join(bundle_dir, bundle.profile["main"])
        bundle_class_name = "SanjiBundle_%s" % (bundle.profile["name"])
        bundleClass = SanjiKeeper.get_sanji_class(bundle_class_name, pyfile)

        if bundleClass is None:
            raise RuntimeError("Couldn't find Sanji subclass in " + pyfile)

        # start the bundle and pass stop_event
        # Note: Here may block by broken class instance init()
        #       Currently, global bootstrap watchdog will handles.
        bInstance = bundleClass(
            bundle=bundle, stop_event=stop_event, connection=connection)

        thread = Thread(target=bInstance.start)
        thread.daemon = True
        thread.start()

        if bundle.profile.get("concurrent", True) is False:
            _logger.debug("Waitting for none concurrent bundle: %s" %
                          bundle.profile["name"])
            bInstance.is_ready.wait(timeout=30)

        return BundleMeta(
            thread, stop_event, connection, bInstance)

    def boot_all(self, bundles, bundle_sequence, connection_class=Mqtt):
        bundle_count = 0
        for bundle_path in bundle_sequence:
            if self.running_bundles.get(bundle_path, None) is not None:
                _logger.info("Skip booting bundle from [%s]..." % bundle_path)
                continue

            connection = connection_class()
            _logger.info("Boot bundle from [%s]..." % bundle_path)
            try:
                self.running_bundles[bundle_path] = self.boot(
                    bundle=bundles[bundle_path],
                    bundle_dir=bundle_path,
                    connection=connection)
            except Exception as e:
                _logger.info(str(e))
                continue

            bundle_count = bundle_count + 1

        _logger.info("Waitting for all bundles...")
        bundle_timeout = 60
        for bundleName, meta in self.running_bundles.iteritems():
            if not meta.instance.is_ready.wait(timeout=bundle_timeout):
                bundle_timeout = 0
                bundle_count = bundle_count - 1
                _logger.info("Bundle %s register timeout" % (bundleName,))

        _logger.info("Total: %s bundles registered." % bundle_count)

    def stop(self):
        map(lambda bundle: bundle.stop_event.set(),
            self.running_bundles.itervalues())
        map(lambda bundle: bundle.thread.join(),
            self.running_bundles.itervalues())

    def start(self, bundles_home, omitted_bundle_names=[]):
        envs = {}
        for key, value in os.environ.items():
            envs[key] = value

        _logger.info(json.dumps(envs))
        _logger.info("Start loading bundles at %s", bundles_home)

        # Scan all bundle.json
        bundle_paths = SanjiKeeper.get_bundle_paths(bundles_home)

        # Load all bunlde.json and create Bundle instance
        bundles = SanjiKeeper.get_bundles(
            bundle_paths, omitted_bundle_names=omitted_bundle_names)

        # Sort bundle using priority in bundle.json
        sorted_bundle_paths = SanjiKeeper.sort_bundles(bundles)
        _logger.info("%s bundle configs are loaded." % len(bundles))
        self.boot_all(bundles=bundles, bundle_sequence=sorted_bundle_paths)
        self.is_booted = True
        _logger.info("Boot all done.")


def watchdog(keeper):
    sleep(DEFAULT_BUNDLE_BOOT_TIMEOUT)
    if keeper.is_booted is False:
        _logger.warning("Boot all timeout. Service restarting...")
        os.execlp("service", "service", "uc8100-mxcloud-cg", "restart")

    _logger.info("Watchdog has been destroyed.")


def load_mode_config(path):
    """Load mode config from pre-defined json file"""
    with open(os.path.join(path, "config", "mode.json")) as f:
        mode = json.load(f)

    return mode


_SYSTEM_MODE_SCHEMA = Schema({
    "enableMode": All(Any(str, unicode), Length(min=1))
}, extra=REMOVE_EXTRA)


class Index(Sanji):

    def init(self, *args, **kwargs):
        self.path_root = os.path.abspath(os.path.dirname(__file__))
        self.model = ModelInitiator("bootstrap", self.path_root)
        self.modes_config = load_mode_config(self.path_root)
        self.keeper = SanjiKeeper()

    def start_keeper(self):
        bundles_home = os.getenv(
            "BUNDLES_HOME", os.path.dirname(__file__) +
            "/tests/mock_bundles/")
        _logger.info("enableMode: %s" % self.model.db["enableMode"])
        watchdog_thread = Thread(target=watchdog, args=[self.keeper])
        watchdog_thread.daemon = True
        watchdog_thread.start()
        self.keeper.start(
            bundles_home,
            self.modes_config[self.model.db["enableMode"]].get(
                "omittedBundleNames", []))

    def run(self):
        if self.model.db["enableMode"] not in self.modes_config:
            _logger.info("enableMode is not set. Waitting...")
            return

        self.start_keeper()

    def before_stop(self):
        if self.keeper:
            self.keeper.stop()

    @Route(resource="/system/sanjikeeper", methods="get")
    def get(self, message, response):
        response(
            data=[meta.instance.bundle.profile for meta
                  in self.keeper.running_bundles.itervalues()])

    @Route(resource="/system/mode", methods="get")
    def get_system_mode(self, message, response):
        response(data=self.model.db)

    @Route(resource="/system/mode", methods="put")
    def put_system_mode(
            self, message, response, schema=_SYSTEM_MODE_SCHEMA):
        mode_name = message.data["enableMode"]
        if mode_name not in self.modes_config:
            response(code=400, data={"message": "Mode is not exist."})
            return

        if self.model.db["enableMode"] != "none":
            response(
                code=400,
                data={"message":
                      "Can't change system mode. Please reset to default."})
            return

        self.model.db["enableMode"] = mode_name
        self.model.save_db()
        self.start_keeper()
        response(data=self.model.db)

if __name__ == '__main__':
    path_root = os.path.abspath(os.path.dirname(__file__))
    with open(
        os.path.join(
            path_root,
            "config/logger-%s.json" % os.getenv("BUNDLE_ENV", "debug")),
            'rt') as f:
        config = json.load(f)
        logging.config.dictConfig(config)
    try:
        index = Index(connection=Mqtt())
        index.start()
    except Exception as e:
        _logger.error(str(e))
        _logger.warning("Bootstrap crashed. Service restarting...")
        os.execlp("service", "service", "uc8100-mxcloud-cg", "restart")
