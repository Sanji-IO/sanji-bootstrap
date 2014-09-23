#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os
import logging
import imp
from threading import Thread
from threading import Event


try:
    # sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../../')
    from sanji.core import Sanji
    from sanji.bundle import Bundle
    from sanji.connection.mqtt import Mqtt
except ImportError:
    print "Please check the python PATH for import Bootstrap module. (%s)" \
        % __file__
    exit(1)

logger = logging.getLogger()


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
        child_bundles = get_bundles(child_dir_path)
        if len(child_bundles) > 0:
            # concat two list
            bundles = bundles + child_bundles

    return bundles


def boot(*args, **kwargs):
    bundle_dir = kwargs.get("bundle_dir")
    stop_event = kwargs.get("stop_event", Event())
    connection = kwargs.get("connection", Mqtt())
    # load bundle information from json config
    bundle = Bundle(bundle_dir=bundle_dir)
    class_name, ext = os.path.splitext(bundle.profile["main"])
    pyfile = os.path.join(bundle_dir, bundle.profile["main"])

    # dynamic load import module via property "main" in bundle config
    m = imp.load_source(class_name.title(), pyfile)

    # start the bundle and pass stop_event
    bundleInstance = getattr(m, class_name.title())(stop_event=stop_event,
                                                    connection=connection)
    thread = Thread(target=bundleInstance.start)
    thread.daemon = True
    thread.start()

    return (thread, stop_event)


class Bootstrap(Sanji):

    def init(self,
             bundle_env=os.getenv("BUNDLE_ENV", "debug"),
             bundle_root_dir=os.getenv("BUNDLE_DIR",
                                       os.path.normpath(__file__ +
                                                        '/../../'))):
        self.bundle_root_dir = bundle_root_dir
        self.bundle_env = bundle_env
        self.running_bundle = {}
        self.bundles = []

    def run(self):
        logger.info("Start loading bundles at %s", self.bundle_root_dir)
        self.bundles = get_bundles(self.bundle_root_dir)
        self.boot_all()
        logger.info("%s bundle config is loaded." % len(self.bundles))

    def boot_all(self, connection_class=None):
        if connection_class is None:
            connection_class = self._conn.__class__

        bundle_count = 0
        for bundle in self.bundles:
            if self.running_bundle.get(bundle, None) is not None:
                logger.info("Skip booting bundle from [%s]..." % bundle)
                continue
            connection = connection_class()
            thread, stop_event = boot(bundle_dir=bundle,
                                      connection=connection)
            self.running_bundle[bundle] = {
                "thread": thread,
                "stop_event": stop_event,
                "connection": connection
            }
            bundle_count = bundle_count + 1
            logger.info("Boot bundle from [%s]..." % bundle)
        logger.info("Total: %s bundles." % bundle_count)

    def before_stop(self):
        map(lambda bundle: bundle["stop_event"].set(),
            self.running_bundle.itervalues())
        map(lambda bundle: bundle["thread"].join(),
            self.running_bundle.itervalues())


if __name__ == '__main__':
    FORMAT = '%(asctime)s - %(levelname)s - %(lineno)s - %(message)s'
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger('Bootstrap')

    bootstrap = Bootstrap()
    bootstrap.start()
