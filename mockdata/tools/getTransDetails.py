# -*- coding: utf-8 -*-
"""
脚本用途：
本脚本用于模拟银行系统或业务系统链路交易数据的生成与发送。
"""
import sys
import os

_THIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import re
import yaml
import json
import logging
import time
import base64
import random
import argparse
from datetime import datetime, timedelta
from kafka import KafkaProducer

from comms.config_loader import load_common_config, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

data_dict = {
    "10001000007_06": "统一收费",
    "12003000019_09": "信用卡客户资料查询/维护",
    "12002000017_03": "提交电子缴印申请",
    "05003000002_18": "客户消息发送平台短信签约查询",
    "04002000016_03": "信用卡账单寄送地址设定",
    "03002000013_01": "手机号支付信息验证",
    "03003000005_14": "城银清交易状态查询",
    "01001000001_01": "卡卡或卡折转账",
    "17002000005_09": "事后监督多种凭证图片识别",
    "04003000003_02": "信用卡未出账单交易明细查询",
    "04003000003_03": "信用卡账单交易明细查询",
    "03005000005_11": "跨行转账汇兑",
    "03001000007_01": "对私跨行转账",
    "08001000003_02": "理财产品购买",
    "10002000002_30": "贷款归还",
    "10002000002_08": "验印远程授权审核结果通知",
    "10002000008_06": "其他业务远程授权",
    "10002000021_03": "贷款开户",
    "10002000002_01": "电子凭证盖章",
    "12003000003_03": "信用卡客户地址查询/维护",
    "08001000003_04": "理财产品赎回",
    "10003000002_01": "电子印章信息查询",
    "10003000009_08": "对公账户全生命周期影像查询",
    "03003000005_27": "国内信用证业务状态及回单打印列表查询",
    "03003000005_09": "查询查看查询",
    "03003000002_95": "国内信用证通知信息查询",
}

default_src_ip = "192.168.1.2"
default_dst_ip = "192.168.2.2"
default_center = "一中心"


def load_config(yaml_file):
    with open(yaml_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _expand_config_vars(config, instances, instance_names):
    """递归展开配置中的 {object_name_N} 和 {object_id_N} 变量。"""
    instance_names = instance_names or {}
    instances = instances or []

    def _name_for(idx):
        if idx < len(instances):
            return instance_names.get(instances[idx], instances[idx])
        return ""

    def _id_for(idx):
        return instances[idx] if idx < len(instances) else ""

    def _expand_str(s):
        s = re.sub(r'\{object_name_(\d+)\}', lambda m: _name_for(int(m.group(1))), s)
        s = re.sub(r'\{object_id_(\d+)\}', lambda m: _id_for(int(m.group(1))), s)
        return s

    def _walk(value):
        if isinstance(value, str):
            return _expand_str(value)
        elif isinstance(value, dict):
            return {_walk(k): _walk(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(config)


def generate_glb_seq_no(link_name):
    ts = int(time.time() * 1000)
    year = str(datetime.now().year)
    base64_link = base64.urlsafe_b64encode(link_name.encode()).decode()
    if len(base64_link) > 10:
        base64_link = base64_link[:10]
    return f"{year}{base64_link}{ts}"


def get_random_value(value, default):
    if isinstance(value, list) and value:
        return random.choice(value)
    elif value:
        return value
    return default


def is_in_abnormal_range(time_range, current_dt):
    if not time_range:
        return False
    now_time = current_dt.time()
    start = datetime.strptime(time_range.get("start"), "%H:%M:%S").time()
    end = datetime.strptime(time_range.get("end"), "%H:%M:%S").time()
    return start <= now_time <= end


def get_trans_status_and_msg(svc, current_dt):
    time_range = svc.get("time_abnormal_range")
    if is_in_abnormal_range(time_range, current_dt):
        status = random.choice(["0", "0", "0", "0", "1"])
        msg = "交易成功" if status == "1" else random.choice(["交易失败", "二维码不存在", "系统繁忙", "超时"])
    else:
        if random.random() < 0.02:
            status = "0"
            msg = random.choice(["网络波动", "后端服务无响应", "数据库连接超时"])
        else:
            status = "1"
            msg = "交易成功"
    return status, msg


def generate_req_resp(src_ip, dst_ip):
    src_port = random.randint(1024, 65535)
    dst_port = random.randint(1024, 65535)

    req_body = {
        "Vlan": random.randint(3000, 4000),
        "DestIp": dst_ip,
        "SrcPort": src_port,
        "DestPort": dst_port,
        "FlowId": f"{random.randint(1,9999999999999999999)}:{random.randint(1,9999999999999999999)}:0",
        "RRA": "req",
        "Prot": "http",
        "transaction_id": f"{random.randint(1,9999999999999999999)}:{random.randint(1,9999999999999999999)}:0",
        "Access-Control-Expose-Headers": "traceRequest",
        "Cache-Control": "no-cache",
        "CodeMessage": "",
        "Connection": "keep-alive",
        "Content-Language": "zh-CN",
        "Content-Length": random.randint(1000, 80000),
        "Content-Type": "application/json",
        "Date": datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "DecodeId": random.randint(100000, 999999),
        "Expires": "Thu, 01 Jan 1970 00:00:00 GMT",
        "IpId": random.randint(10000, 99999),
        "Keep-Alive": "timeout=60",
        "NicNsTs": 0,
        "PL": 1,
        "PktId": random.randint(1000000000, 9999999999),
        "Pragma": "No-cache",
        "SrcIp": src_ip,
    }

    return req_body, src_port, dst_port


def generate_data(config, data_dict, base_time=None):
    results = []
    if base_time is None:
        base_time = datetime.now()

    base_ms = base_time.microsecond // 1000

    for link_name, systems in config.items():
        glb_seq_no = generate_glb_seq_no(link_name)
        trans_code, trans_type = random.choice(list(data_dict.items()))

        for system, services in systems.items():
            for svc in services:
                ms_offset = int(svc.get('ms', 0))
                total_ms = base_ms + ms_offset

                dt_with_ms = base_time.replace(microsecond=0) + timedelta(milliseconds=total_ms)

                timestamp = dt_with_ms.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                trans_status, ret_msg = get_trans_status_and_msg(svc, dt_with_ms)
                ret_code = "200" if trans_status == "1" else "404"

                resptime_obj = dt_with_ms + timedelta(seconds=0.5)
                resp_time = resptime_obj.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                long_time_str = str(int(resptime_obj.timestamp() * 1000000))

                src_ip = get_random_value(svc.get("src_ip", []), default_src_ip)
                dst_ip = get_random_value(svc.get("dst_ip", []), default_dst_ip)

                req_body, src_port, dst_port = generate_req_resp(src_ip, dst_ip)

                resp_body = req_body.copy()
                resp_body.update({
                    "RRA": "resp",
                    "RetCode": ret_code,
                    "TransStatus": trans_status,
                    "RetMsg": ret_msg,
                    "TransactionId": req_body["transaction_id"],
                    "Content-Length": random.randint(1000, 80000),
                    "RespTime": resp_time,
                })

                record = {
                    "longTime": long_time_str,
                    "timestamp": timestamp,
                    "req_time": timestamp,
                    "resp_time": resp_time,
                    "system": system,
                    "service_name": svc["service_name"],
                    "up_link": svc.get("up_link", ""),
                    "duration": round(random.uniform(3, 11), 3),
                    "src_ip": src_ip,
                    "dst_ip": dst_ip,
                    "center": get_random_value(svc.get("center", []), default_center),
                    "glb_seq_no": glb_seq_no,
                    "trans_status": trans_status,
                    "ret_code": ret_code,
                    "ret_msg": ret_msg,
                    "trans_code": trans_code,
                    "trans_type": trans_type,
                    "extend": {
                        "src_ip": src_ip,
                        "src_port": src_port,
                        "dst_ip": dst_ip,
                        "dst_port": dst_port,
                        "ret_code": ret_code,
                        "ret_msg": ret_msg,
                        "trans_status": trans_status,
                        "center": get_random_value(svc.get("center", []), default_center),
                        "req_body": req_body,
                        "resp_body": resp_body,
                    },
                }
                results.append(record)
    return results


def run(mockdata_dir, instances=None, instance_names=None,
        start=None, end=None, debug=False, kafka_broker=None):
    """运行链路交易数据生成。mockdata_dir 用于定位 config/trans_details_service.yaml。"""
    try:
        yaml_path = os.path.join(mockdata_dir, 'config', 'trans_details_service.yaml') if mockdata_dir else None
        if not yaml_path or not os.path.exists(yaml_path):
            logger.error("trans_details_service.yaml not found at %s", yaml_path)
            return False
        config = load_config(yaml_path)

        if instances:
            config = _expand_config_vars(config, instances, instance_names)

        cfg = load_common_config(mockdata_dir)
        if not kafka_broker:
            kafka_broker = cfg.get('kafka', {}).get('brokers')
        topic = DEFAULT_CONFIG['topics']['trans_details']

        producer = None
        if kafka_broker and not debug:
            producer = KafkaProducer(
                bootstrap_servers=kafka_broker,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            )

        if start and end:
            try:
                start_time = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
                end_time = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                print("时间格式错误，请使用 YYYY-MM-DD HH:MM:SS")
                return False

            current_time = start_time
            while current_time <= end_time:
                if current_time.microsecond == 0:
                    print(f"正在生成 {current_time.strftime('%Y-%m-%d %H:%M:%S')} 的数据...")

                data = generate_data(config, data_dict, current_time)
                for record in data:
                    if debug:
                        print(f"调试数据: {json.dumps(record, ensure_ascii=False)},\n")
                    elif producer:
                        producer.send(topic, record)
                current_time += timedelta(seconds=0.5)

            if producer and not debug:
                producer.flush()
                producer.close()
            print("时间范围数据生成完成。")
        else:
            if debug:
                data = generate_data(config, data_dict)
                for record in data:
                    print(f"调试数据: {json.dumps(record, ensure_ascii=False)},\n")
            else:
                try:
                    while True:
                        data = generate_data(config, data_dict)
                        for record in data:
                            producer.send(topic, record)
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    print("停止发送数据。")
                finally:
                    if producer:
                        producer.flush()
                        producer.close()

        return True
    except Exception as e:
        print(f"链路数据生成失败: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="链路数据生成器")
    parser.add_argument("--config", type=str, default="config/trans_details_service.yaml",
                        help="YAML 配置文件路径")
    parser.add_argument("--debug", action="store_true", help="调试模式，只运行一次并打印数据")
    parser.add_argument("--start", type=str, help="开始时间 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, help="结束时间 (格式: YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args()

    _dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    success = run(
        mockdata_dir=_dir,
        start=args.start,
        end=args.end,
        debug=args.debug,
    )
    sys.exit(0 if success else 1)
