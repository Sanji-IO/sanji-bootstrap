#!/usr/bin/env python
# -*- coding: UTF-8 -*-


import os
import sys
import unittest
import logging

from threading import Event
from mock import patch
from mock import Mock

try:
    sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../')
    from bootstrap import SanjiKeeper
    from bootstrap import BundleMeta
    from sanji.connection.mockup import Mockup
except ImportError as e:
    print "Please check the python PATH for import test module. (%s)" \
        % __file__
    exit(1)

dirpath = os.path.dirname(os.path.realpath(__file__))


class TestSanjiKeeperClass(unittest.TestCase):

    def setUp(self):
        os.putenv("BUNDLE_DIR", dirpath + "/mock_bundles/")
        self.sanjikeeper = SanjiKeeper()

    def tearDown(self):
        self.sanjikeeper.stop()
        self.sanjikeeper = None

    def test_get_bundles(self):
        root_path = os.path.dirname(os.path.realpath(__file__)) + \
            '/mock_bundles/'
        root_path = os.path.normpath(root_path)
        self.assertEqual(len(self.sanjikeeper.get_bundles(root_path)), 1)

    @patch("bootstrap.Thread")
    def test_boot(self, Thread):
        Thread.return_value = Mock()
        options = {
            "bundle_dir": os.path.normpath(dirpath + "/mock_bundles/bundle_1"),
            "connection": Mockup(),
            "stop_event": Event()
        }
        meta = self.sanjikeeper.boot(**options)
        self.assertIsInstance(meta, BundleMeta)

    @patch("bootstrap.SanjiKeeper.boot")
    def test_boot_all(self, boot):
        boot.return_value = BundleMeta
        (None, Event().set(), None, Mock(is_ready=Event().set()))
        self.sanjikeeper.boot_all(Mockup)


if __name__ == "__main__":
    FORMAT = '%(asctime)s - %(levelname)s - %(lineno)s - %(message)s'
    logging.basicConfig(level=20, format=FORMAT)
    logger = logging.getLogger('SanjiKeeper')
    unittest.main()
