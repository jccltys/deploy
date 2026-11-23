# -*- coding: utf-8 -*-
"""
基础指标生成器 (refactored)
"""
import sys
import os
import json
import time
import random
import argparse
from datetime import datetime, timedelta

import yaml
from kafka import KafkaProducer

from comms.object_reader import load_object_ids_by_type
from comms.logger import generator_logger as logger
from comms.topic_manager import ensure_topics
from comms.config_loader import load_common_config, DEFAULT_CONFIG

class BasicMetricsGenerator:
    """基础指标生成器"""

    def __init__(self, object_ids_by_type, metrics_yaml_path, kafka_broker=None, debug=False,
                 topics=None):
        self.object_ids_by_type = object_ids_by_type
        self.kafka_broker = kafka_broker
        self.debug = debug
        self.topics = topics or {}

        with open(metrics_yaml_path, 'r', encoding='utf-8') as f:
            self.metrics_list = yaml.safe_load(f)

        logger.info("Loaded %d metric definitions from %s",
                     len(self.metrics_list), metrics_yaml_path)
        logger.info("Object types loaded: %s", list(object_ids_by_type.keys()))
        logger.info("Kafka broker: %s", self.kafka_broker)

        self._producer = None

    @property
    def producer(self):
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self.kafka_broker,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
            )
        return self._producer

    def ensure_topics(self):
        topics = [(t, 3) for t in self.topics.values()]
        ensure_topics(broker=self.kafka_broker, topic_defs=topics)

    def generate_and_send(self, start_time=None, end_time=None):
        if start_time is None and end_time is None:
            logger.info("Entering infinite loop mode (Ctrl+C to stop)")
            try:
                while True:
                    now = datetime.now()
                    self._generate_batch(now)
                    logger.info("Batch done at %s, sleeping 60s...", now)
                    if self.debug:
                        break
                    time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Stopped by user")
        else:
            current = start_time
            while current <= end_time:
                self._generate_batch(current)
                current += timedelta(minutes=1)
            logger.info("Range mode completed: %s ~ %s", start_time, end_time)

    def _generate_batch(self, current_time):
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamp = timestamp[:17] + "1" + timestamp[18:]

        if self.debug:
            print(f"\n--- DEBUG [{timestamp}] ---")

        for metric in self.metrics_list:
            metric_type = metric.get("type")
            metric_source = metric.get("source", "")
            metric_name = metric.get("metricName", "")
            default_config = metric.get("default", {})
            dimension = metric.get("dimension") or None

            topic = self.topics.get(metric_name)
            if not topic:
                continue

            object_ids = self.object_ids_by_type.get(metric_type, [])
            if not object_ids:
                continue

            for object_id in object_ids:
                value = self._compute_value(default_config, object_id, current_time)

                data = {
                    "timestamp": timestamp,
                    "objectId": object_id,
                    "metric": metric_source,
                    "value": value,
                }

                if dimension:
                    data[dimension] = f"{dimension}_{random.randint(1, 10)}"

                if self.debug:
                    print(json.dumps(data, ensure_ascii=False))
                else:
                    self._produce(topic, data, object_id)

        if not self.debug:
            self.producer.flush()

    def _compute_value(self, config, object_id, current_time):
        if not config:
            return random.randint(40, 60)

        if "value" not in config:
            if any(key in config for key in ("min", "max", "objectIds", "timeRange")):
                return self._compute_flat_default(config, None, object_id, current_time)
            return random.randint(40, 60)

        value_cfg = config["value"]

        if isinstance(value_cfg, (int, float)) or value_cfg is None:
            return self._compute_flat_default(config, value_cfg, object_id, current_time)

        if isinstance(value_cfg, dict):
            if "timeRange" in value_cfg:
                time_ranges = value_cfg["timeRange"]
                if isinstance(time_ranges, list):
                    for tr in time_ranges:
                        if not isinstance(tr, dict):
                            continue
                        start = tr.get("start", 0)
                        end = tr.get("end", 0)
                        tr_value = tr.get("value", 0)
                        obj_ids = tr.get("objectIds", [])
                        if obj_ids and object_id not in obj_ids:
                            continue
                        if self._time_in_range(start, end, current_time):
                            return tr_value
                    last = time_ranges[-1]
                    return last.get("value", 0) if isinstance(last, dict) else 0

            if "min" in value_cfg and "max" in value_cfg:
                obj_ids = value_cfg.get("objectIds", [])
                if obj_ids and object_id not in obj_ids:
                    return config.get("value", 0) if isinstance(config.get("value"), (int, float)) else 0
                return round(random.uniform(value_cfg["min"], value_cfg["max"]), 1)

            if "objectIds" in value_cfg:
                obj_ids = value_cfg["objectIds"]
                if object_id in obj_ids:
                    return value_cfg.get("value", 0)
                return 0

        return 0

    def _compute_flat_default(self, config, default_value, object_id, current_time):
        """value 为数字时的平级结构：timeRange 时间段 + min/max 区间 + objectIds 过滤"""
        time_range = config.get("timeRange")
        if time_range and not self._time_in_range(
                time_range.get("start"), time_range.get("end"), current_time):
            return default_value if default_value is not None else random.randint(40, 60)

        min_val = config.get("min")
        max_val = config.get("max")
        if min_val is not None and max_val is not None:
            obj_ids = config.get("objectIds", [])
            if obj_ids and object_id not in obj_ids:
                return default_value if default_value is not None else random.randint(40, 60)
            return round(random.uniform(min_val, max_val), 1)

        return default_value if default_value is not None else random.randint(40, 60)

    @staticmethod
    def _time_in_range(start, end, current_time):
        """时间段判断（左闭右开），兼容整数小时（0-23）与 "HH:MM"/"HH:MM:SS" 字符串"""
        if start is None or end is None:
            return True

        def _to_seconds(value):
            if isinstance(value, (int, float)):
                return int(value) * 3600
            parts = str(value).split(":")
            total = int(parts[0]) * 3600 + int(parts[1]) * 60
            if len(parts) > 2:
                total += int(parts[2])
            return total

        now_sec = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        start_sec = _to_seconds(start)
        end_sec = _to_seconds(end)
        if start_sec <= end_sec:
            return start_sec <= now_sec < end_sec
        return now_sec >= start_sec or now_sec < end_sec

    def _produce(self, topic, data, key):
        try:
            self.producer.send(topic, key=key.encode('utf-8'), value=data)
        except Exception as e:
            logger.error("Produce failed: %s", e)


def run(mockdata_dir, object_ids_by_type,
        start=None, end=None, debug=False, kafka_broker=None,
        create_topics=False):
    """
    运行基础指标生成。
    mockdata_dir: mockdata/ 目录路径，用于定位 config/basic_metric_type.yaml
    """
    try:
        metrics_yaml = os.path.join(mockdata_dir, 'config', 'basic_metric_type.yaml')
        if not os.path.exists(metrics_yaml):
            logger.error("basic_metric_type.yaml not found: %s", metrics_yaml)
            return False

        cfg = load_common_config(mockdata_dir)
        topics_map = {"基础监控": "infra_metrics_aiops", "APM": "apm_metrics_aiops"}

        if not kafka_broker:
            kafka_broker = cfg.get('kafka', {}).get('brokers')

        gen = BasicMetricsGenerator(
            object_ids_by_type=object_ids_by_type,
            metrics_yaml_path=metrics_yaml,
            kafka_broker=kafka_broker,
            debug=debug,
            topics=topics_map,
        )

        if create_topics:
            gen.ensure_topics()

        if start and end:
            try:
                start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.error("时间格式错误, 应为 YYYY-MM-DD HH:MM:SS")
                return False
            gen.generate_and_send(start_time=start_dt, end_time=end_dt)
        else:
            gen.generate_and_send()

        return True
    except Exception as e:
        logger.error("基础指标生成失败: %s", e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="基础指标生成器")
    parser.add_argument("--debug", action="store_true", help="调试模式，仅打印数据，不发送 Kafka")
    parser.add_argument("-ct", "--create-topics", action="store_true",
                        help="启动时自动创建 Kafka topics")
    parser.add_argument("--start", type=str, default=None, help="开始时间 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, default=None, help="结束时间 (格式: YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args()

    _dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _xlsx_dir = os.path.join(_dir, '..', 'lib', 'odmp')
    _xlsx_file = None
    if os.path.isdir(_xlsx_dir):
        for fname in os.listdir(_xlsx_dir):
            if fname.startswith("10-aiops-objectInstance") and fname.endswith(".xlsx"):
                _xlsx_file = os.path.join(_xlsx_dir, fname)
                break
    if not _xlsx_file or not os.path.exists(_xlsx_file):
        logger.error("xlsx file not found in %s", _xlsx_dir)
        sys.exit(1)

    _object_ids_by_type = load_object_ids_by_type(_xlsx_file)
    if not _object_ids_by_type:
        logger.error("No object IDs loaded, exiting")
        sys.exit(1)

    success = run(
        mockdata_dir=_dir,
        object_ids_by_type=_object_ids_by_type,
        start=args.start,
        end=args.end,
        debug=args.debug,
        create_topics=args.create_topics,
    )
    sys.exit(0 if success else 1)
