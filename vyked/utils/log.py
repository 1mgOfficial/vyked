from logging import Handler
from queue import Queue
from threading import Thread
import logging.config
import logging
import asyncio
import aiotask_context as context
import datetime
import yaml
import sys
import os

from functools import partial, wraps
from pythonjsonlogger import jsonlogger


RED = '\033[91m'
BLUE = '\033[94m'
BOLD = '\033[1m'
END = '\033[0m'

_BRANCH_NAME = None
http_pings_logs_disabled = True

def http_ping_filter(record):
    if "GET /ping/" in record.getMessage():
       return 0
    return 1


class LogFormatHelper:
    LogFormat = '%a %t "%r" %s %b %D "%{Referer}i" "%{User-Agent}i" %{X-Request-ID}i'


class CustomTimeLoggingFormatter(logging.Formatter):

    def formatTime(self, record, datefmt=None):  # noqa
        """
        Overrides formatTime method to use datetime module instead of time module
        to display time in microseconds. Time module by default does not resolve
        time to microseconds.
        """
        
        record.branchname = _BRANCH_NAME

        if datefmt:
            s = datetime.datetime.now().strftime(datefmt)
        else:
            t = datetime.datetime.now().strftime(self.default_time_format)
            s = self.default_msec_format % (t, record.msecs)
        return s


class CustomJsonFormatter(jsonlogger.JsonFormatter):

    def __init__(self, *args, **kwargs):
        self.extrad = kwargs.pop('extrad', {})
        super().__init__(*args, **kwargs)

    def add_fields(self, log_record, record, message_dict):
        message_dict.update(self.extrad)
        record.branchname = _BRANCH_NAME
        super().add_fields(log_record, record, message_dict)


def patch_async_emit(handler: Handler):
    base_emit = handler.emit
    queue = Queue()

    def loop():
        while True:
            record = queue.get()
            try:
                base_emit(record)
            except:
                print(sys.exc_info())

    def async_emit(record):
        queue.put(record)

    thread = Thread(target=loop)
    thread.daemon = True
    thread.start()
    handler.emit = async_emit
    return handler


def patch_add_handler(logger):
    base_add_handler = logger.addHandler

    def async_add_handler(handler):
        async_handler = patch_async_emit(handler)
        base_add_handler(async_handler)

    return async_add_handler


DEFAULT_CONFIG_YAML = """
    # logging config

    version: 1
    disable_existing_loggers: False
    handlers:
        stream:
            class: logging.StreamHandler
            level: INFO
            formatter: ctf
            stream: ext://sys.stdout

        stats:
            class: logging.FileHandler
            level: INFO
            formatter: cjf
            filename: logs/vyked_stats.log

        exceptions:
            class: logging.FileHandler
            level: INFO
            formatter: cjf
            filename: logs/vyked_exceptions.log

        service:
            class: logging.FileHandler
            level: INFO
            formatter: ctf
            filename: logs/vyked_service.log

    formatters:
        ctf:
            (): vyked.utils.log.CustomTimeLoggingFormatter
            format: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            datefmt: '%Y-%m-%d %H:%M:%S,%f'

        cjf:
            (): vyked.utils.log.CustomJsonFormatter
            format: '{ "timestamp":"%(asctime)s", "message":"%(message)s"}'
            datefmt: '%Y-%m-%d %H:%M:%S,%f'

    root:
        handlers: [stream, service]
        level: INFO

    loggers:
        registry:
            handlers: [service,]
            level: INFO

        stats:
            handlers: [stats]
            level: INFO

        exceptions:
            handlers: [exceptions]
            level: INFO

    """

def setup_logging(_):
    try:
        with open('config_log.json', 'r') as f:
            config_dict = yaml.load(f.read())
    except:
        config_dict = yaml.load(DEFAULT_CONFIG_YAML)

    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logger = logging.getLogger()
    logger.handlers = []
    logger.addHandler = patch_add_handler(logger)

    logging.config.dictConfig(config_dict)

    if http_pings_logs_disabled:
        for handler in logging.root.handlers:
            handler.addFilter(http_ping_filter)