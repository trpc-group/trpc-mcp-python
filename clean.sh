#!/bin/bash

sudo rm  -rf  coverage.xml
sudo rm  -rf  *.log
sudo rm  -rf  htmlcov
sudo rm  -rf  .coverage
sudo rm  -rf  .__*
sudo rm  -rf  trpc_mcp.egg-info
sudo rm  -rf dist/
sudo rm  -rf build/


sudo rm  -rf  test_tracemalloc*
sudo rm  -rf  test-ngtest-ut-trpc_mcp*
sudo rm  -rf  cov.tmp
sudo rm  -rf  example/*.lock
sudo rm  -rf  example/*.log
sudo rm  -rf  example/mcp_server/*.lock
sudo rm  -rf  example/mcp_server/*.log
sudo rm  -rf  example/trpc_server/*.lock
sudo rm  -rf  example/trpc_server/*.log

sudo rm  -rf  example/.__py_trpc_frame.lock
sudo rm  -rf  example/.__trpc.lock


find -type d | grep __pycache__ | xargs sudo rm  -r

find ./ -type f -name "*.log" -exec sudo rm {} \;
