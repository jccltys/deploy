# -*- coding: utf-8 -*-
"""
日志模块 — 同时输出到控制台和日志文件（带轮转），支持 JSON 格式
"""
import json
import logging
import os
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    """JSON 格式日志输出器"""
    def format(self, record):
        log_entry = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'component': getattr(record, 'component', ''),
            'host': getattr(record, 'host', ''),
            'message': record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logger(log_dir, name='deploy', debug=False, json_log=False):
    """初始化日志器，同时输出到文件和控制台"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'deploy.log')

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    logger.handlers.clear()

    if json_log:
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    fh = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if debug else logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger
