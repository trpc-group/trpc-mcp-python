# -*- coding: utf-8 -*-
"""This is server module"""

import os
import sys
import argparse
from typing import List

import trpc
from trpc.log import logger

# add the stub to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_callback")))  # noqa
if __name__ != '__main__':  # noqa
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))  # noqa

# import sdk and plugins
# pylint: disable=unused-import
import trpc_naming_polaris as _
import trpc_mcp
# DO NOT remove the plugin below!
# import trpc_metrics_runtime as _
# pylint: enable=unused-import

from mcp_callback import tools as _
from mcp_callback import resources as _
from mcp_callback import prompts as _
from filters import EchoToolFilter as _
# 普通 trpc HTTP 服务路由（仅当某个 service 以 protocol: http 监听时才生效）。
# 导入即注册；在纯 http_mcp 配置下不会绑定到任何监听，无副作用。
import http_service as _

# argparse parser
parser = argparse.ArgumentParser(description='TRPC Python Framework Server')

DEFAULT_CONF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "trpc_python.yaml"))

# define config file argument
parser.add_argument('--conf',
                    '-c',
                    default=DEFAULT_CONF_PATH,
                    help='start server with conf, for example: `python3 trpc_main.py  --conf=trpc_python.yaml`')


def parse_args(argv: List[str]):
    """Parse the command line arguments
    :param argv: command line arguments
    """
    try:
        args = parser.parse_args(argv[1:])  # Skip the script name
        if os.path.exists(args.conf):
            print(f"conf_path: {args.conf}")
            return args.conf
        print(f"conf_path: {args.conf} not exists")
        if os.path.exists(DEFAULT_CONF_PATH):
            print(f"use default conf path: {DEFAULT_CONF_PATH}")
            return DEFAULT_CONF_PATH
        print(f"default conf path: {DEFAULT_CONF_PATH} not exists, please check the path")
        sys.exit(1)
    except SystemExit:
        # argparse will call sys.exit() when --help is used or invalid args
        sys.exit(1)


def serve(conf_path: str):
    """Serve the server
    :param conf_path: configuration file path
    """

    svr = trpc.new(conf_path)

    trpc_mcp.register_trpc_mcp_server(svr, None)

    svr.serve()


def main():
    """Main function"""

    # parse the command line arguments
    conf_path = parse_args(sys.argv)
    logger.info("load config %s", conf_path)

    # serve the server
    serve(conf_path)


if __name__ == '__main__':
    sys.exit(main())
