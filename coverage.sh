#!/bin/sh

sh +x build.sh

pip3 install build

pip3 install -r requirements-test.txt

rm -rf coverage.xml
rm -rf test-ngtest-ut-trpc_mcp.xml
rm -rf .coverage
rm -rf htmlcov*


test_dir=trpc_mcp
pytest --cov-report html --cov-report term --cov-report xml --cov=$test_dir tests/  \
       --junitxml=test-ngtest-ut-$test_dir.xml > cov.tmp
status=$?
if [ $status -ne 0 ]; then
    if [ -f cov.tmp ]; then
        echo "pytest failed, dumping cov.tmp:"
        cat cov.tmp
    fi
    exit $status
fi
