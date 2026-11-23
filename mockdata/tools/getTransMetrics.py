# -*- coding: utf-8 -*-
"""
交易指标生成器 (refactored)
"""
import sys
import os

# 确保本模块所在目录在 sys.path 中，使 `from comms.xxx` 导入可用
_THIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import json
import re
import time
import random
import argparse
from datetime import datetime, timedelta

import yaml
from kafka import KafkaProducer

from comms.logger import generator_logger as logger
from comms.config_loader import load_common_config, DEFAULT_CONFIG

class TransMetricsGenerator:
    """交易指标生成器"""

    def __init__(self, instances, config_path, kafka_broker=None, debug=False,
                 instance_names=None, topic=None):
        self.instances = instances
        self.instance_names = instance_names or {}
        self.kafka_broker = kafka_broker
        self.debug = debug
        self.topic = topic or "bpm_trans_metrics_aiops"

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        raw_cases = self.config.get("cases", {})
        self.cases = self._expand_cases(raw_cases, instances)
        self.start_date = datetime(2025, 9, 11)

        logger.info("Loaded %d cases from %s", len(self.cases), config_path)
        logger.info("Instances count: %d", len(instances))
        logger.info("Kafka broker: %s", self.kafka_broker)

        self._producer = None

    @staticmethod
    def _expand_cases(raw_cases, instances, instance_names=None):
        """Expand template variables in case keys and values.

        - '{object_id_N}' (e.g. {object_id_0}, {object_id_1}) maps to instances[N].
        - '{object_id}' (no index) expands to ALL instances (catch-all).
        - '{object_name}' in values is replaced with the instance name.
        """
        instance_names = instance_names or {}
        expanded = {}
        for key, config in raw_cases.items():
            idx_match = re.search(r'\{object_id_(\d+)\}', key)
            if idx_match:
                idx = int(idx_match.group(1))
                if idx < len(instances):
                    instance_id = instances[idx]
                    real_key = key.replace(idx_match.group(0), instance_id)
                    name = instance_names.get(instance_id, instance_id)
                    expanded[real_key] = TransMetricsGenerator._replace_vars(config, instance_id, name)
            elif '{object_id}' in key:
                for instance_id in instances:
                    real_key = key.replace('{object_id}', instance_id)
                    name = instance_names.get(instance_id, instance_id)
                    expanded[real_key] = TransMetricsGenerator._replace_vars(config, instance_id, name)
            else:
                expanded[key] = TransMetricsGenerator._replace_vars(config, None, None)
        return expanded

    @staticmethod
    def _replace_vars(value, instance_id, instance_name):
        if isinstance(value, str):
            result = value
            if instance_id is not None and '{object_id}' in result:
                result = result.replace('{object_id}', instance_id)
            if instance_name is not None and '{object_name}' in result:
                result = result.replace('{object_name}', instance_name)
            return result
        elif isinstance(value, dict):
            return {
                k: TransMetricsGenerator._replace_vars(v, instance_id, instance_name)
                for k, v in value.items()
            }
        elif isinstance(value, list):
            return [
                TransMetricsGenerator._replace_vars(item, instance_id, instance_name)
                for item in value
            ]
        return value

    @property
    def producer(self):
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self.kafka_broker,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
            )
        return self._producer

    def generate_and_send(self, start_time=None, end_time=None):
        if start_time is None and end_time is None:
            logger.info("Entering infinite loop mode (Ctrl+C to stop)")
            try:
                while True:
                    now = datetime.now()
                    self._send_batch(now)
                    logger.info("Batch done at %s, sleeping 60s...", now)
                    if self.debug:
                        break
                    time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Stopped by user")
        else:
            current = start_time
            while current <= end_time:
                logger.info("Generating data for %s", current.strftime("%Y-%m-%d %H:%M"))
                self._send_batch(current)
                current += timedelta(minutes=1)
            logger.info("Range mode completed: %s ~ %s", start_time, end_time)

    def _send_batch(self, current_time):
        metrics_data = self._generate_metrics(current_time)
        if self.debug:
            print(f"\n--- DEBUG [{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ---")
            for entry in metrics_data:
                print(json.dumps(entry, ensure_ascii=False))
        else:
            for entry in metrics_data:
                try:
                    self.producer.send(self.topic, value=entry)
                except Exception as e:
                    logger.error("Produce failed: %s", e)
            self.producer.flush()

    def _generate_metrics(self, now):
        hhmm = now.strftime("%H:%M")
        even_day = self._is_even_day(now)
        data = []

        for instance in self.instances:
            if even_day:
                data.append(self._generate_normal_metrics(instance, now))
                continue

            case_info = self.cases.get(instance, {})
            applied = self._resolve_case(case_info, hhmm, now, instance)
            if applied is not None:
                data.append(applied)
            else:
                data.append(self._generate_normal_metrics(instance, now))

        return data

    def _resolve_case(self, case_info, hhmm, now, instance_id):
        for special in case_info.get("special", []):
            baseline_times = {b["time"] for b in case_info.get("baseline", [])}
            if special["baseline_time"] not in baseline_times:
                continue
            if hhmm in special["times"]:
                idx = special["times"].index(hhmm)
                return self._generate_from_case(now, instance_id, {
                    "count": special["count"][idx],
                    "duration": special["duration"][idx],
                    "resp_rate": special["resp_rate"][idx],
                    "succ_rate": special["succ_rate"][idx],
                })

        for b in case_info.get("baseline", []):
            if b["time"] == hhmm:
                return self._generate_from_case(now, instance_id, b)

        return None

    def _generate_from_case(self, now, instance_id, case):
        trans_count = case["count"]
        response_rate = case["resp_rate"] / 100
        success_rate = case["succ_rate"] / 100
        trans_response = int(trans_count * response_rate)
        trans_success = int(trans_response * success_rate)
        trans_duration = int(case["duration"] * trans_success)

        return {
            "timestamp": (now + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "objectId": instance_id,
            "transCountByMinute": trans_count,
            "transDurationByMinute": trans_duration,
            "transResponseCountByMinute": trans_response,
            "transSuccessCountByMinute": trans_success,
            "transResponseRateByMinute": case["resp_rate"],
            "transSuccessRateByMinute": case["succ_rate"],
        }

    def _generate_normal_metrics(self, instance, now):
        trans_count = random.randint(2000, 3000)
        response_rate = round(random.uniform(0.96, 1.0), 4)
        success_rate = round(random.uniform(0.97, 1.0), 4)
        trans_response = int(trans_count * response_rate)
        trans_success = int(trans_response * success_rate)
        trans_duration = int(trans_count * random.uniform(0.2, 0.5))

        return {
            "timestamp": (now + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "objectId": instance,
            "transCountByMinute": trans_count,
            "transDurationByMinute": trans_duration,
            "transResponseCountByMinute": trans_response,
            "transSuccessCountByMinute": trans_success,
            "transResponseRateByMinute": round(response_rate * 100, 2),
            "transSuccessRateByMinute": round(success_rate * 100, 2),
        }

    def _is_even_day(self, dt):
        delta_days = (dt.date() - self.start_date.date()).days
        return delta_days % 2 == 0


def run(mockdata_dir, instances, instance_names=None,
        start=None, end=None, debug=False, kafka_broker=None):
    """
    运行交易指标生成。
    mockdata_dir: mockdata/ 目录路径，用于定位 config/trans_metric.yaml
    """
    try:
        config_path = os.path.join(mockdata_dir, 'config', 'trans_metric.yaml')
        if not os.path.exists(config_path):
            logger.error("trans_metric.yaml not found: %s", config_path)
            return False

        cfg = load_common_config(mockdata_dir)
        if not kafka_broker:
            kafka_broker = cfg.get('kafka', {}).get('brokers')

        gen = TransMetricsGenerator(
            instances=instances,
            config_path=config_path,
            kafka_broker=kafka_broker,
            debug=debug,
            instance_names=instance_names,
            topic=DEFAULT_CONFIG['topics']['trans_metrics'],
        )

        if start and end:
            try:
                start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.error("时间格式错误，应为 YYYY-MM-DD HH:MM:SS")
                return False
            gen.generate_and_send(start_time=start_dt, end_time=end_dt)
        else:
            gen.generate_and_send()

        return True
    except Exception as e:
        logger.error("交易指标生成失败: %s", e)
        return False


if __name__ == "__main__":
    from comms.object_reader import load_object_ids_by_type

    parser = argparse.ArgumentParser(description="交易指标生成器")
    parser.add_argument("--debug", action="store_true", help="调试模式，仅打印数据，不发送 Kafka")
    parser.add_argument("--start", type=str, help="开始时间 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, help="结束时间 (格式: YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args()

    _dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _dir)

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

    _all_ids = load_object_ids_by_type(_xlsx_file)
    _instances = _all_ids.get("Biz_system", [])
    if not _instances:
        logger.error("No Biz_system instances found in xlsx, using fallback list")
        _instances = [
            "10u3hkl5m9xf0bk", "10u3hkl5m9xf1bk", "10u3hkl5m9xf2bk",
            "10u3hkl5m9xf3bk", "10u3hkl5m9xf4bk", "10u3hkl5m9xf5bk",
            "10u3hkl5m9xf6bk", "10u3hkl5m9xf7bk",
            "10u3hkl5m9xf0zq", "10u3hkl5m9xf1zq", "10u3hkl5m9xf2zq",
            "10u3hkl5m9xf3zq", "10u3hkl5m9xf4zq", "10u3hkl5m9xf5zq",
        ]

    success = run(
        mockdata_dir=_dir,
        instances=_instances,
        start=args.start,
        end=args.end,
        debug=args.debug,
    )
    sys.exit(0 if success else 1)
