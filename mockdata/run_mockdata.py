# -*- coding: utf-8 -*-
"""
Mock 数据统一启动脚本

功能：
1. 统一加载 xlsx 数据，各模块共用
2. 自动检测 Kafka 地址，创建 topic
3. 直接调用各模块（无 subprocess 开销）

用法：
    # 运行全部模块
    python3 run_mockdata.py

    # 仅运行指定模块
    python3 run_mockdata.py alert
    python3 run_mockdata.py alert itsm-devops

    # 调试模式
    python3 run_mockdata.py --debug

    # 指定时间范围
    python3 run_mockdata.py --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

    # 指定对象实例 xlsx 文件
    python3 run_mockdata.py --xlsx /path/to/objectInstance.xlsx

    # 组合参数：指定 xlsx + 时间范围 + 特定模块
    python3 run_mockdata.py alert metrics --xlsx /path/to/objectInstance.xlsx --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
"""
import argparse
from datetime import datetime
import os
import sys
import threading
import time
from kafka.errors import NoBrokersAvailable

MOCKDATA_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, MOCKDATA_DIR)

from comms.object_reader import load_object_ids_by_type, load_object_detail
from comms.topic_manager import ensure_topics
from comms.logger import runner_logger as logger
from comms.config_loader import load_common_config, DEFAULT_CONFIG

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class MockDataRunner:

    MODULES = {
        'alert': ('告警数据', 'tools.getAlert'),
        'metrics': ('基础指标', 'tools.getBasicMetrics'),
        'trans-metrics': ('交易指标', 'tools.getTransMetrics'),
        'trans-details': ('交易链路明细', 'tools.getTransDetails'),
        'itsm-devops': ('ITSM & DevOps', 'tools.getItsmDevops'),
        'fixed-alert': ('固定告警', 'tools.getFixedAlerts'),
    }

    def __init__(self, debug=False,
                 start=None, end=None, xlsx_path=None):
        self.debug = debug
        self.start = start
        self.end = end
        self.xlsx_path = xlsx_path
        cfg = load_common_config(MOCKDATA_DIR)
        self._common_cfg = cfg
        self.kafka_broker = cfg.get('kafka', {}).get('brokers')
        if not self.kafka_broker:
            logger.warning('无法检测 Kafka 地址，将继续运行')

    def _validate_time_format(self, value, name):
        try:
            datetime.strptime(value, TIME_FORMAT)
        except ValueError:
            logger.error("%s 时间格式错误，应为 YYYY-MM-DD HH:MM:SS，收到: %s", name, value)
            sys.exit(1)

    def _load_xlsx_data(self):
        """加载 xlsx 一次，返回各模块所需的数据字典。"""
        if self.xlsx_path:
            xlsx_file = self.xlsx_path
        else:
            xlsx_dir = os.path.join(MOCKDATA_DIR, '..', 'lib', 'odmp')
            xlsx_file = None
            if os.path.isdir(xlsx_dir):
                for fname in os.listdir(xlsx_dir):
                    if fname.startswith("10-aiops-objectInstance") and fname.endswith(".xlsx"):
                        xlsx_file = os.path.join(xlsx_dir, fname)
                        break

        object_ids_by_type = {}
        object_detail = {}
        if xlsx_file and os.path.exists(xlsx_file):
            object_ids_by_type = load_object_ids_by_type(xlsx_file)
            object_detail = load_object_detail(xlsx_file)

        # biz_node_mapping for alert
        biz_node_mapping = {}
        for oid, detail in object_detail.items():
            if detail.get('_sheet') == '业务系统':
                name = detail.get('对象名称', '')
                biz_node_mapping[oid] = name + '-应用' if name else ''

        # system_names for itsm-devops
        system_names = []
        biz_instance_names = {}
        for oid, detail in object_detail.items():
            if detail.get('_sheet') == '业务系统':
                name = detail.get('对象名称')
                if name and isinstance(name, str) and name.strip():
                    system_names.append(name.strip())
                    biz_instance_names[oid] = name.strip()

        return {
            'object_ids_by_type': object_ids_by_type,
            'biz_node_mapping': biz_node_mapping,
            'biz_instances': object_ids_by_type.get('Biz_system', []),
            'system_names': system_names,
            'biz_instance_names': biz_instance_names,
        }

    def _import_module(self, module_name):
        """动态导入模块并返回其 run 函数。"""
        import_path = self.MODULES[module_name][1]
        mod = __import__(import_path, fromlist=['run'])
        return mod.run

    def run(self, selected_modules):
        """运行指定模块列表，不传则运行全部。每个模块在独立线程中并行执行。"""
        if self.start:
            self._validate_time_format(self.start, '--start')
        if self.end:
            self._validate_time_format(self.end, '--end')
        if (self.start and not self.end) or (self.end and not self.start):
            logger.error("--start 和 --end 必须同时指定，不能只使用一个")
            return False

        if selected_modules:
            modules_to_run = []
            for m in selected_modules:
                if m in self.MODULES:
                    modules_to_run.append(m)
                else:
                    logger.error('未知模块: %s，可用模块: %s',
                                 m, ', '.join(sorted(self.MODULES.keys())))
                    return False
        else:
            modules_to_run = sorted(self.MODULES.keys())

        if not self.debug and self.kafka_broker:
            alert_topics = DEFAULT_CONFIG['topics']['alert']
            required = [
                (alert_topics['data'], 3),
                (alert_topics['rule'], 3),
                (alert_topics['unialert'], 1),
            ]
            try:
                ensure_topics(self.kafka_broker, required)
            except NoBrokersAvailable:
                logger.warning("Kafka 不可用，跳过 topic 创建")

        # 加载 xlsx 数据（只加载一次，各线程共享）
        xlsx_data = self._load_xlsx_data()
        if not xlsx_data['object_ids_by_type']:
            logger.warning("未加载到 xlsx 对象数据，部分模块可能无法正常运行")

        threads = []
        for module_name in modules_to_run:
            t = threading.Thread(
                target=self._run_single_module,
                args=(module_name, xlsx_data),
                daemon=True,
            )
            t.start()
            threads.append(t)

        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            logger.info("收到终止信号，主线程退出（daemon 线程自动结束）")

        return True

    def _run_single_module(self, module_name, xlsx_data):
        """在独立线程中运行单个模块。"""
        label = self.MODULES[module_name][0]
        logger.info('启动 %s [%s]', module_name, label)

        try:
            run_func = self._import_module(module_name)
        except Exception as e:
            logger.error('导入模块 %s 失败: %s', module_name, e)
            return

        kwargs = {
            'mockdata_dir': MOCKDATA_DIR,
            'start': self.start,
            'end': self.end,
            'debug': self.debug,
        }

        # 各模块特有参数
        if module_name == 'alert':
            kwargs['object_ids_by_type'] = xlsx_data['object_ids_by_type']
            kwargs['biz_node_mapping'] = xlsx_data['biz_node_mapping']
            kwargs['kafka_broker'] = self.kafka_broker
        elif module_name == 'metrics':
            kwargs['object_ids_by_type'] = xlsx_data['object_ids_by_type']
            kwargs['kafka_broker'] = self.kafka_broker
        elif module_name == 'trans-metrics':
            kwargs['instances'] = xlsx_data['biz_instances']
            kwargs['instance_names'] = xlsx_data['biz_instance_names']
            kwargs['kafka_broker'] = self.kafka_broker
        elif module_name == 'itsm-devops':
            kwargs['system_names'] = xlsx_data['system_names']
        elif module_name == 'trans-details':
            kwargs['instances'] = xlsx_data['biz_instances']
            kwargs['instance_names'] = xlsx_data['biz_instance_names']
            kwargs['kafka_broker'] = self.kafka_broker
        elif module_name == 'fixed-alert':
            kwargs['kafka_broker'] = self.kafka_broker

        try:
            ok = run_func(**kwargs)
            if not ok:
                logger.error('%s 运行失败', module_name)
        except Exception as e:
            logger.error('%s 运行异常: %s', module_name, e)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Mock 数据统一启动脚本')
    parser.add_argument('--xlsx', type=str, default=None,
                        help='对象实例 xlsx 文件路径（默认自动查找 lib/odmp/10-aiops-objectInstance_*.xlsx）')
    parser.add_argument('--debug', action='store_true',
                        help='调试模式（透传给各脚本）')
    parser.add_argument('--start', type=str, default=None,
                        help='开始时间。格式: YYYY-MM-DD HH:MM:SS')
    parser.add_argument('--end', type=str, default=None,
                        help='结束时间。格式: YYYY-MM-DD HH:MM:SS')
    parser.add_argument('modules', nargs='*',
                        help='要运行的模块: {} (默认全部)'.format(
                            ', '.join(sorted(MockDataRunner.MODULES.keys()))))
    args = parser.parse_args()

    runner = MockDataRunner(
        debug=args.debug,
        start=args.start,
        end=args.end,
        xlsx_path=args.xlsx,
    )

    if not runner.run(args.modules):
        sys.exit(1)
