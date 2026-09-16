#!/bin/bash

python3 -m pip install --upgrade pip

pip3 install yapf


find ./trpc_mcp -name '*.py' -print0 | xargs -0 yapf -i
find ./tests -name '*.py' -print0 | xargs -0 yapf -i
find ./examples -name '*.py' -print0 | xargs -0 yapf -i
