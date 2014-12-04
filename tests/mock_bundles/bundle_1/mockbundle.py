#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import logging

try:
    from sanji.core import Sanji
    from sanji.core import Route
except ImportError:
    print "Please check the python PATH for import Bootstrap module. (%s)" \
        % __file__
    exit(1)

logger = logging.getLogger()


class Mockbundle(Sanji):

    def init(self, *args, **kwargs):
        self.message = "Hello Sanji!"

    @Route(methods="get", resource="/hellosanji")
    def get555(self, message, response):
        response(data={"message": self.message})

    @Route(methods="put", resource="/hellosanji")
    def put(self, message, response):
        if hasattr(message, "data"):
            self.message = message.data["message"]
            return response()
        return response(code=400, data={"message": "Invaild Input."})
