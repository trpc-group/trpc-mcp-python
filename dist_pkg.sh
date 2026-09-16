#!/bin/sh

INIT_PY="trpc_mcp/version.py"

version=$(grep -oP "__version__ = '\K[^']+" "$INIT_PY")

sudo rm -rf dist
echo "version is ${version}"

sh +x build.sh
pip3 install build

pip3 install urllib3

pip3 install twine
# dist source package
#python -m build --sdist
# dist wheel pacakge
python -m build


twine upload dist/* -r tencent
