# -*- coding: utf-8 -*-
"""
Mock 数据公共日志模块

按组件分文件输出，每个文件保留 3 个备份，最大 10MB。

使用方式：
    from logger import runner_logger as logger
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')

_FMT = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


def _setup_logger(name, filename):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    os.makedirs(LOG_DIR, exist_ok=True)

    console = logging.StreamHandler()
    console.setFormatter(_FMT)
    logger.addHandler(console)

    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, filename),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
    )
    fh.setFormatter(_FMT)
    logger.addHandler(fh)

    return logger


runner_logger = _setup_logger('mockdata.runner', 'runner.log')
topic_logger = _setup_logger('mockdata.topic', 'topic.log')
generator_logger = _setup_logger('mockdata.generator', 'generator.log')
