#!/usr/bin/env python
# -*- coding: UTF-8 -*-


import os
import sys
import unittest
import logging


try:
    sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../')
    from bootstrap import Bootstrap
    from bootstrap import get_bundles
    from bootstrap import boot
    from sanji.connection.mockup import Mockup
except ImportError as e:
    print os.path.dirname(os.path.realpath(__file__)) + '/../'
    print sys.path
    print e
    print "Please check the python PATH for import test module. (%s)" \
        % __file__
    exit(1)

dirpath = os.path.dirname(os.path.realpath(__file__))


class TestFunctions(unittest.TestCase):

    def test_get_bundles(self):
        root_path = os.path.dirname(os.path.realpath(__file__)) + \
            '/mock_bundles/'
        root_path = os.path.normpath(root_path)
        self.assertEqual(len(get_bundles(root_path)), 1)

    def test_boot(self):
        options = {
            "bundle_dir": os.path.normpath(dirpath + "/mock_bundles/bundle_1"),
            "connection": Mockup(),
        }
        thread, stop_event = boot(**options)
        thread.join(0.1)
        self.assertTrue(thread.is_alive())
        stop_event.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class TestBootstrapClass(unittest.TestCase):

    def setUp(self):
        os.putenv("BUNDLE_DIR", dirpath + "/mock_bundles/")
        self.bootstrap = Bootstrap(connection=Mockup())

    def tearDown(self):
        self.bootstrap.stop()
        self.bootstrap = None

    def test_init(self):
        pass

    def test_run(self):
        self.bootstrap.run()

    def test_boot_all(self):
        self.bootstrap.boot_all(Mockup)


if __name__ == "__main__":
    FORMAT = '%(asctime)s - %(levelname)s - %(lineno)s - %(message)s'
    logging.basicConfig(level=20, format=FORMAT)
    logger = logging.getLogger('Bootstrap Test')
    unittest.main()
