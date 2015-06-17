#!/usr/bin/env python
# -*- coding: UTF-8 -*-

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

from sanji.core import Sanji
from sanji.core import Route
from sanji.bundle import Bundle
from sanji.connection.mqtt import Mqtt

logger = logging.getLogger("sanji.bootstrap")

BundleMeta = namedtuple(
    'BundleMeta', 'thread, stop_event, connection, instance')


class SanjiKeeper(object):

    def __init__(self):
        self.running_bundles = {}

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
    def get_bundles(bundle_paths):
        """
        Load all bundle.json from given bundle_paths
        Return dict() key=path, value=Bundle instance
        """
        bundles = {}
        for path in bundle_paths:
            bundles[path] = Bundle(bundle_dir=path)

        return bundles

    @staticmethod
    def get_sanji_class(class_name, pyfile):

        def predicate(member):
            return inspect.isclass(member) and \
                issubclass(member, Sanji)

        # dynamic load import module via property "main" in bundle config
        module = imp.load_source(class_name.title(), pyfile)
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

        class_name, ext = os.path.splitext(bundle.profile["main"])

        if class_name == "bootstrap":
            raise RuntimeError("ignore class: bootstrap")
        if ext != ".py":
            raise RuntimeError("ignore none python bundle: %s" % ext)

        # Append bundle path into sys.path
        sys.path.append(bundle_dir)
        pyfile = os.path.join(bundle_dir, bundle.profile["main"])
        bundleClass = SanjiKeeper.get_sanji_class(class_name, pyfile)

        if bundleClass is None:
            raise RuntimeError("Couldn't find Sanji subclass in " + pyfile)

        # start the bundle and pass stop_event
        bInstance = bundleClass(
            bundle=bundle, stop_event=stop_event, connection=connection)

        thread = Thread(target=bInstance.start)
        thread.daemon = True
        thread.start()

        if bundle.profile.get("concurrent", True) is False:
            logger.debug("Waitting for none concurrent bundle: %s" %
                         bundle.profile["name"])
            bInstance.is_ready.wait(timeout=30)

        return BundleMeta(
            thread, stop_event, connection, bInstance)

    def boot_all(self, bundles, bundle_sequence, connection_class=Mqtt):
        bundle_count = 0
        for bundle_path in bundle_sequence:
            if self.running_bundles.get(bundle_path, None) is not None:
                logger.info("Skip booting bundle from [%s]..." % bundle_path)
                continue

            connection = connection_class()
            logger.info("Boot bundle from [%s]..." % bundle_path)
            try:
                self.running_bundles[bundle_path] = self.boot(
                    bundle=bundles[bundle_path],
                    bundle_dir=bundle_path,
                    connection=connection)
            except Exception as e:
                logger.info(str(e))
                continue

            bundle_count = bundle_count + 1

        logger.info("Waitting for all bundles...")
        bundle_timeout = 60
        for bundleName, meta in self.running_bundles.iteritems():
            if not meta.instance.is_ready.wait(timeout=bundle_timeout):
                bundle_timeout = 0
                bundle_count = bundle_count - 1
                logger.info("Bundle %s register timeout" % (bundleName,))

        logger.info("Total: %s bundles registered." % bundle_count)

    def stop(self):
        map(lambda bundle: bundle.stop_event.set(),
            self.running_bundles.itervalues())
        map(lambda bundle: bundle.thread.join(),
            self.running_bundles.itervalues())

    def start(self, bundles_home):
        envs = {}
        for key, value in os.environ.items():
            envs[key] = value

        logger.info(json.dumps(envs))
        logger.info("Start loading bundles at %s", bundles_home)

        # Scan all bundle.json
        bundle_paths = SanjiKeeper.get_bundle_paths(bundles_home)
        # Load all bunlde.json and create Bundle instance
        bundles = SanjiKeeper.get_bundles(bundle_paths)
        # Sort bundle using priority in bundle.json
        sorted_bundle_paths = SanjiKeeper.sort_bundles(bundles)

        self.boot_all(bundles=bundles, bundle_sequence=sorted_bundle_paths)
        logger.info("%s bundle config is loaded." % len(bundles))


class Index(Sanji):

    def init(self, *args, **kwargs):
        self.keeper = SanjiKeeper()

    def run(self):
        bundles_home = os.getenv("BUNDLES_HOME", os.path.dirname(__file__) +
                                 '/tests/mock_bundles/')
        self.keeper.start(bundles_home)

    def before_stop(self):
        self.keeper.stop()

    @Route(resource="/system/sanjikeeper", methods="get")
    def get(self, message, response):
        response(
            data=[meta.instance.bundle.profile for meta
                  in self.keeper.running_bundles.itervalues()])

if __name__ == '__main__':
    path_root = os.path.abspath(os.path.dirname(__file__))
    with open(
        os.path.join(
            path_root,
            "config/logger-%s.json" % os.getenv("BUNDLE_ENV", "debug")),
            'rt') as f:
        config = json.load(f)
        logging.config.dictConfig(config)

    index = Index(connection=Mqtt())
    index.start()
