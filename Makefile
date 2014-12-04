all: pylint test

pylint:
	flake8 -v .
test:
	nosetests --with-coverage --cover-package=bootstrap

.PHONY: pylint test
