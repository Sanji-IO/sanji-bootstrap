#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os
import logging
import imp
import inspect
from collections import namedtuple
from threading import Thread
from threading import Event

from sanji.core import Sanji
from sanji.core import Route
from sanji.bundle import Bundle
from sanji.connection.mqtt import Mqtt

logger = logging.getLogger()
BundleMeta = namedtuple(
    'BundleMeta', 'thread, stop_event, connection, instance')


class SanjiKeeper(object):

    def __init__(self):
        self.running_bundles = {}
        self.bundles = []

    @staticmethod
    def get_bundles(dir_path):
        dirs = []
        for file in os.listdir(dir_path):
            if file == "bundle.json":
                return [dir_path]
            child_dir_path = os.path.join(dir_path, file)
            if os.path.isdir(child_dir_path):
                dirs.append(child_dir_path)

        # if this dir has no exist bundle.json file, then go deeper
        bundles = []
        for child_dir_path in dirs:
            child_bundles = SanjiKeeper.get_bundles(child_dir_path)
            if len(child_bundles) > 0:
                # concat two list
                bundles = bundles + child_bundles

        return bundles

    @staticmethod
    def get_sanji_class(class_name, pyfile):

        def predicate(member):
            return inspect.isclass(member) and \
                issubclass(member, Sanji)

        # dynamic load import module via property "main" in bundle config
        module = imp.load_source(class_name.title(), pyfile)
        result = inspect.getmembers(module, predicate)
        return None if len(result) == 0 else result[0][1]

    def boot(*args, **kwargs):
        bundle_dir = kwargs.get("bundle_dir")
        stop_event = kwargs.get("stop_event", Event())
        connection = kwargs.get("connection", Mqtt())

        # load bundle information from json config
        bundle = Bundle(bundle_dir=bundle_dir)
        class_name, ext = os.path.splitext(bundle.profile["main"])

        if class_name == "bootstrap":
            raise RuntimeError("ignore class: bootstrap")
        if ext != ".py":
            raise RuntimeError("ignore none python bundle: %s" % ext)

        pyfile = os.path.join(bundle_dir, bundle.profile["main"])
        bundleClass = SanjiKeeper.get_sanji_class(class_name, pyfile)

        if bundleClass is None:
            raise RuntimeError("Couldn't find Sanji subclass in " + pyfile)

        # start the bundle and pass stop_event
        bInstance = bundleClass(stop_event=stop_event, connection=connection)
        thread = Thread(target=bInstance.start)
        thread.daemon = True
        thread.start()

        return BundleMeta(
            thread, stop_event, connection, bInstance)

    def boot_all(self, connection_class=Mqtt):
        bundle_count = 0
        for bundle in self.bundles:
            if self.running_bundles.get(bundle, None) is not None:
                logger.info("Skip booting bundle from [%s]..." % bundle)
                continue
            connection = connection_class()

            try:
                self.running_bundles[bundle] = self.boot(
                    bundle_dir=bundle, connection=connection)
            except Exception as e:
                logger.info(e)
                continue

            bundle_count = bundle_count + 1
            logger.info("Boot bundle from [%s]..." % bundle)

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
        logger.info("Start loading bundles at %s", bundles_home)
        self.bundles = SanjiKeeper.get_bundles(bundles_home)
        self.boot_all()
        logger.info("%s bundle config is loaded." % len(self.bundles))


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
    FORMAT = '%(asctime)s - %(levelname)s - %(lineno)s - %(message)s'
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger('SanjiKeeper')

    index = Index(connection=Mqtt())
    index.start()
