# -*- coding: utf-8 -*-
"""
固定告警生成器 — 每天生产一批固定内容的告警

与 getAlert.py 的随机生成不同，本脚本生产 6 条内容固定的告警
（演示/演练场景），每次运行生成一批后退出，建议通过 crontab 每天调度一次。

用法:
    # 直接运行（发送当天日期的 6 条告警到 Kafka）
    python3 tools/getFixedAlerts.py

    # 调试模式（只打印，不发送）
    python3 tools/getFixedAlerts.py --debug

    # 指定日期（默认当天）
    python3 tools/getFixedAlerts.py --date 2026-09-10
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kafka import KafkaProducer

from comms.logger import generator_logger as logger
from comms.config_loader import load_common_config, DEFAULT_CONFIG
from comms.topic_manager import ensure_topics

# 6 条固定告警（alertTime 只含时分秒毫秒，运行日期在发送时拼接）
FIXED_ALERTS = [
    {
        "alertSource": "基础监控",
        "alertDescription": "Linux-172.25.161.110主机CPU使用率96.3%，超过阈值85%且持续5分钟",
        "alertTitle": "CPU使用率异常",
        "alertTime": "10:02:15.000",
        "alertLevel": 5,
        "objectId": "23u3hkl5m9xf00bk",
        "metric": "system.cpu.pct_usage",
        "ip": "172.25.161.110",
    },
    {
        "alertSource": "基础监控",
        "alertDescription": "manage-172.25.161.110应用进程连接数1850，超过阈值1000",
        "alertTitle": "应用进程连接数异常",
        "alertTime": "10:04:10.000",
        "alertLevel": 5,
        "objectId": "16u3hkl5m9xf00bk",
        "metric": "system.process.count",
        "ip": "172.25.161.110",
    },
    {
        "alertSource": "apm",
        "alertDescription": "manage-172.25.161.110应用日志5分钟内出现327次连接池获取超时（Connectionpool timeout）",
        "alertTitle": "连接池超时异常",
        "alertTime": "10:05:40.000",
        "alertLevel": 5,
        "objectId": "16u3hkl5m9xf00bk",
        "metric": "system.connectionpool.timeout.count",
        "ip": "172.25.161.110",
    },
    {
        "alertSource": "apm",
        "alertDescription": "Apache_172.25.161.50_80后端响应504超时占比18.4%，超过阈值2%",
        "alertTitle": "后端响应504超时异常",
        "alertTime": "10:06:05.000",
        "alertLevel": 5,
        "objectId": "12u3hkl5m9xf00bk",
        "metric": "system.http.response.code.504.pct",
        "ip": "172.25.161.50",
    },
    {
        "alertSource": "bpm",
        "alertDescription": "统一收单系统UAS的bpc_duration平均交易耗时1650ms，基线450ms",
        "alertTitle": "交易耗时异常",
        "alertTime": "10:07:00.000",
        "alertLevel": 5,
        "objectId": "10u3hkl5m9xf0bk",
        "metric": "transDurationByMinute",
        "ip": "",
    },
    {
        "alertSource": "bpm",
        "alertDescription": "统一收单系统UAS的bpc交易成功率95.8%，低于阈值99.5%",
        "alertTitle": "交易成功率异常",
        "alertTime": "10:08:20.000",
        "alertLevel": 5,
        "objectId": "10u3hkl5m9xf0bk",
        "metric": "transSuccessCountByMinute",
        "ip": "",
    },
]


def generate_alert_id():
    """生成 12 位随机告警 ID"""
    return ''.join(random.choices("0123456789", k=12))


def build_alert_message(item, date_str):
    """组装完整告警消息（alertTime 拼接运行日期）"""
    return {
        "alertId": generate_alert_id(),
        "objectId": item["objectId"],
        "ip": item["ip"],
        "metric": item["metric"],
        "alertTitle": item["alertTitle"],
        "alertDescription": item["alertDescription"],
        "alertSource": item["alertSource"],
        "alertTime": "{} {}".format(date_str, item["alertTime"]),
        "alertLevel": item["alertLevel"],
        "extend49": item.get("extend49", ""),
    }


def _generate_batch(alerts_topic, date_str, debug, kafka_broker):
    """生成并发送一批 6 条固定告警"""
    producer = None
    if not debug:
        ensure_topics(kafka_broker, [(alerts_topic, 3)])
        producer = KafkaProducer(
            bootstrap_servers=kafka_broker,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
        )

    for item in FIXED_ALERTS:
        message = build_alert_message(item, date_str)
        if debug:
            logger.info("[固定告警] %s", message)
        else:
            producer.send(alerts_topic, message)

    if producer:
        producer.flush()
        producer.close()

    logger.info("固定告警生成完成: 日期 %s, 共 %d 条", date_str, len(FIXED_ALERTS))


def run(mockdata_dir=None, debug=False, date=None, kafka_broker=None,
        start=None, end=None):
    """生成固定告警并发送到 Kafka（参考 itsm-devops 的每日循环模式）

    启动后立即生成一批，之后每 24 小时生成一批；告警时间（时分秒毫秒）
    固定，日期取当天。传 start/end（时间范围模式）或 debug 时仅执行一次。

    Args:
        mockdata_dir: mockdata/ 目录路径，用于定位 common_config.yaml
        debug: 调试模式，只打印不发送，执行一次即退出
        date: 告警日期（YYYY-MM-DD），默认当天
        kafka_broker: Kafka broker 地址，默认从 common_config.yaml 读取
        start: 兼容 run_mockdata 统一入口透传，无 date 时取其日期部分
        end: 兼容 run_mockdata 统一入口透传，本脚本不使用

    Returns:
        bool: 执行成功返回 True
    """
    if mockdata_dir is None:
        mockdata_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        load_common_config(mockdata_dir)
        alerts_topic = DEFAULT_CONFIG['topics']['alert']['data']
        if not debug and not kafka_broker:
            kafka_broker = load_common_config(mockdata_dir).get('kafka', {}).get('brokers')

        if start and end:
            date_str = date or start[:10]
            _generate_batch(alerts_topic, date_str, debug, kafka_broker)
            return True

        while True:
            date_str = date or datetime.now().strftime("%Y-%m-%d")
            _generate_batch(alerts_topic, date_str, debug, kafka_broker)
            if debug:
                break
            logger.info("24小时后生成下一批固定告警...")
            time.sleep(24 * 60 * 60)

        return True
    except Exception as e:
        logger.error("固定告警生成失败: %s", e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='生成固定告警数据（每天一批，发送到 Kafka）')
    parser.add_argument('--debug', action='store_true', help='调试模式，只打印不发送')
    parser.add_argument('--date', type=str, default=None,
                        help='告警日期（YYYY-MM-DD），默认当天')
    args = parser.parse_args()

    success = run(debug=args.debug, date=args.date)
    sys.exit(0 if success else 1)
