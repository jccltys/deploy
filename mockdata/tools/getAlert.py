# -*- coding: utf-8 -*-
"""
告警及规则模拟生成器
"""
import csv
import random
import json
import argparse
import os
import time
from datetime import datetime
from kafka import KafkaProducer

from comms.object_reader import load_object_ids_by_type, load_object_detail
from comms.logger import generator_logger as logger
from comms.config_loader import load_common_config, DEFAULT_CONFIG
from comms.topic_manager import ensure_topics


class AlertDataGenerator:

    def __init__(self, object_ids_by_type, biz_node_mapping, kafka_broker=None):
        self.object_ids_by_type = object_ids_by_type
        self.node_mapping = biz_node_mapping
        self.kafka_broker = kafka_broker

    @staticmethod
    def generate_alert_id():
        return ''.join(random.choices("0123456789", k=12))

    @staticmethod
    def send_alert(alert_message, producer, topic, is_debug):
        if is_debug:
            logger.info("[告警] %s", alert_message)
        else:
            producer.send(topic, alert_message)

    def generate_biz_system_alert(self, metrics, producer, current_time, is_debug, topic):
        object_ids = self.object_ids_by_type.get("Biz_system", [])
        if not object_ids:
            return

        object_id = random.choice(object_ids)
        metric_row = random.choice(metrics)
        _, _, metric_english, metric_source = metric_row

        ip = "192.168.{}.{}".format(random.randint(1, 254), random.randint(1, 254))
        node_name = self.node_mapping.get(object_id, "")

        alert_message = {
            "alertId": self.generate_alert_id(),
            "objectId": object_id,
            "ip": ip,
            "metric": metric_english,
            "alertTitle": "{}告警".format(metric_english),
            "alertDescription": "{}超出正常范围，需立即排查。".format(metric_english),
            "alertSource": metric_source,
            "alertTime": current_time,
            "alertLevel": random.randint(3, 5),
            "extend49": node_name,
        }
        self.send_alert(alert_message, producer, topic, is_debug)

    def generate_alert_rules_from_csv(self, csv_file_path, topic, producer, current_time, is_debug):
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                metric_type = row[0]
                metric_chinese = row[1]
                metric_english = row[2]
                metric_source = row[3]

                object_ids = self.object_ids_by_type.get(metric_type)
                if not object_ids:
                    continue

                for object_id in object_ids:
                    alert_rule = {
                        "source": metric_source,
                        "metric": metric_chinese,
                        "metricId": metric_english,
                        "alertRuleName": "{}_告警".format(metric_english),
                        "alertRuleDesc": "{}超出正常范围，需立即排查。".format(metric_english),
                        "alertCondition": "指标值超过设定阈值",
                        "date": current_time,
                        "objectId": object_id,
                        "type": metric_type,
                    }
                    if is_debug:
                        logger.info("[规则] %s", alert_rule)
                    else:
                        producer.send(topic, alert_rule)

    def generate_alerts_from_csv(self, csv_file_path, topic, producer, current_time, is_debug):
        data_by_type = {}
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                metric_type = row[0]
                if metric_type not in data_by_type:
                    data_by_type[metric_type] = []
                data_by_type[metric_type].append(row)

        if "Biz_system" in data_by_type:
            self.generate_biz_system_alert(
                data_by_type["Biz_system"], producer, current_time, is_debug, topic)

        for metric_type, metrics in data_by_type.items():
            if metric_type == "Biz_system":
                continue
            selected_metrics = random.sample(metrics, 2)
            object_ids = self.object_ids_by_type.get(metric_type, [])
            if not object_ids:
                continue
            object_id = random.choice(object_ids)

            ip = "192.168.{}.{}".format(random.randint(1, 254), random.randint(1, 254))

            for metric_row in selected_metrics:
                _, _, metric_english, metric_source = metric_row
                alert_message = {
                    "alertId": self.generate_alert_id(),
                    "objectId": object_id,
                    "ip": ip,
                    "metric": metric_english,
                    "alertTitle": "{}告警".format(metric_english),
                    "alertDescription": "{}超出正常范围，需立即排查。".format(metric_english),
                    "alertSource": metric_source,
                    "alertTime": current_time,
                    "alertLevel": random.randint(3, 5),
                }
                self.send_alert(alert_message, producer, topic, is_debug)


def run(mockdata_dir, object_ids_by_type, biz_node_mapping,
        start=None, end=None, debug=False, kafka_broker=None):
    """
    运行告警数据生成。
    mockdata_dir: mockdata/ 目录路径，用于定位 config/alert_rule_info.csv
    """
    try:
        csv_file_path = os.path.join(mockdata_dir, 'config', 'alert_rule_info.csv')
        load_common_config(mockdata_dir)
        alert_topics = DEFAULT_CONFIG['topics']['alert']
        alerts_topic = alert_topics['data']
        alerts_rule_topic = alert_topics['rule']

        generator = AlertDataGenerator(
            object_ids_by_type, biz_node_mapping, kafka_broker=kafka_broker)

        if start:
            try:
                datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
                current_time = start
            except ValueError:
                logger.error("--start 参数格式应为 'YYYY-MM-DD HH:MM:SS'")
                return False
        else:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        if not debug:
            ensure_topics(generator.kafka_broker, [(alerts_topic, 3), (alerts_rule_topic, 3)])

        producer = None
        if not debug:
            producer = KafkaProducer(
                bootstrap_servers=generator.kafka_broker,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
            )

        while True:
            if start and end:
                datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
                current_time = start
            else:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            logger.info("使用时间点: %s", current_time)
            generator.generate_alerts_from_csv(
                csv_file_path, alerts_topic, producer, current_time, debug)

            if producer:
                producer.flush()

            # range mode: 单次执行
            if start and end:
                break

            # infinite loop mode: 每3小时执行一次
            if debug:
                break
            logger.info("3小时后生成下一批告警数据...")
            time.sleep(3 * 60 * 60)

        if producer:
            producer.close()
        logger.info("任务执行完成。")
        return True
    except Exception as e:
        logger.error("告警生成失败: %s", e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='生成告警和规则数据')
    parser.add_argument('--debug', action='store_true', help='调试模式，不发送数据到 Kafka')
    parser.add_argument('--start', type=str, help='指定生成告警的时间点 (格式: YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end', type=str, default=None,
                        help='结束时间（兼容统一启动器透传，本脚本不使用）')
    args = parser.parse_args()

    _dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _object_ids_by_type = load_object_ids_by_type()
    _object_detail = load_object_detail()
    _biz_node_mapping = {}
    for oid, detail in _object_detail.items():
        if detail.get('_sheet') == '业务系统':
            name = detail.get('对象名称', '')
            _biz_node_mapping[oid] = name + '-应用' if name else ''

    success = run(
        mockdata_dir=_dir,
        object_ids_by_type=_object_ids_by_type,
        biz_node_mapping=_biz_node_mapping,
        start=args.start,
        end=args.end,
        debug=args.debug,
    )
    sys.exit(0 if success else 1)
