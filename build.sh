#!/bin/bash

pip install --upgrade pip

pip3 uninstall -y trpc_mcp

pip3 install -r requirements.txt
pip3 install -r requirements-test.txt

# The legacy ``xmlrunner`` PyPI package is unmaintained and does not support
# Python 3.12+. Detect the interpreter version and install the maintained
# drop-in replacement ``unittest-xml-reporting`` (which still exposes the
# ``xmlrunner`` import) on 3.12+, while keeping ``xmlrunner`` for older ones.
py_ver=$(python3 -c 'import sys; print("%d%02d" % (sys.version_info[0], sys.version_info[1]))')
if [ "$py_ver" -ge 312 ]; then
    echo "Python $py_ver detected: installing unittest-xml-reporting"
    pip3 install unittest-xml-reporting
else
    echo "Python $py_ver detected: installing xmlrunner"
    pip3 install xmlrunner
fi

pip install -e .  -i  --extra-index-url https://pypi.org/simple/
