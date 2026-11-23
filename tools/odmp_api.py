#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODMP API 工具集 — 封装采集层、建模层和系统配置接口

采集层 IngestionFlow (/api/v2/ingestion):
   数据中心 / 注册中心 / 数据源 / 集群 / 算子包管理
建模层 ImportFlow (/api/v2/data/modeling):
   业务分类 / Excel 数据导入
系统配置 ConfigFlow (/api/v2/systemconfig):
   系统管理配置初始化（Zookeeper / 数据缓存 / 对象模型 / CK宽表 / Nebula等）

命令行用法:
     python3 deploy/tools/odmp_api.py ingestion --api <ip:port> [options]
     python3 deploy/tools/odmp_api.py import --api <ip:port> [options]
     python3 deploy/tools/odmp_api.py config --api <ip:port> [options]
     python3 deploy/tools/odmp_api.py process --api <ip:port>
     python3 deploy/tools/odmp_api.py job --api <ip:port> [options]

代码调用:
    from tools.odmp_api import IngestionFlow
    flow = IngestionFlow('192.168.1.2:9900')
    flow.run(package_dir='/data/softs')

    from tools.odmp_api import ConfigFlow
    flow = ConfigFlow('192.168.1.2:9900')
    flow.run()
"""

import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TOOLS_DIR, '..'))

# ---------------------------------------------------------------------------
# 重新导出 _odmp_api 包中的所有公有类和函数，保持向后兼容
# ---------------------------------------------------------------------------
from tools._odmp_api._base import (                          # noqa: E402
    _logger,
    _ensure_console_handler,
    _type_cn,
    _parse_jar_name_version,
    _CLICKHOUSE_PRIVATE_KEY,
    _PUBLISH_TYPE_MAP,
    CATEGORY_CODE,
    CATEGORY_NAME,
    VALID_MODES,
    _FILE_PATTERN,
    _TYPE_CN_MAP,
    BASE_INGESTION,
    BASE_MODELING,
    BASE_DATA_MODELING,
    BASE_DATA_SERVICE,
    BASE_SYSTEM,
    BASE_WORKFLOW,
    scan_packages,
    scan_workflow_resources,
    scan_import_files,
    scan_import_files_by_keyword,
    BaseAPI,
)
from tools._odmp_api._ingestion import IngestionFlow        # noqa: E402
from tools._odmp_api._import_flow import ImportFlow          # noqa: E402
from tools._odmp_api._config_flow import ConfigFlow          # noqa: E402
from tools._odmp_api._process_update import DataProcessUpdateFlow  # noqa: E402
from tools._odmp_api._job_update import JobUpdateFlow        # noqa: E402

# ---------------------------------------------------------------------------
# CLI 入口 — argparse / main
# ---------------------------------------------------------------------------
import argparse
import logging

from core.config_utils import load_config_file

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)


def _setup_logger():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return root


_FLOW_CLASSES = {
    'ingestion': (IngestionFlow, '采集层初始化（数据中心/集群/算子包）'),
    'import':    (ImportFlow, '建模层导入（业务分类/Excel导入）'),
    'config':    (ConfigFlow, '系统管理配置初始化'),
    'process': (DataProcessUpdateFlow, '数据处理任务配置更新（Kafka/MySQL/CK地址）'),
    'job': (JobUpdateFlow, '弹性作业配置更新（aimeter-alert Nacos/artifacts）'),
}


def main():
    parser = argparse.ArgumentParser(description='ODMP API 工具集')
    sub = parser.add_subparsers(dest='command', title='子命令')

    p_ing = sub.add_parser('ingestion', help='采集层初始化（数据中心/集群/算子包/workflow资源）')
    p_ing.add_argument('--api', required=True, help='API 地址 (IP:Port)')
    p_ing.add_argument('--package-dir', default='.',
                       help='包目录（默认当前目录），扫描 {dir}/job/{jar,python,data,workflow}')
    p_ing.add_argument('--list', action='store_true', help='列出已上传的内置算子包，不上传')
    p_ing.add_argument('--builtin-only', action='store_true',
                       help='仅注册内置算子包，不上传本地非内置包')
    p_ing.add_argument('--local-only', action='store_true',
                       help='仅上传本地非内置包，不注册内置包')

    p_imp = sub.add_parser('import', help='建模层导入（业务分类/Excel导入）')
    p_imp.add_argument('--api', required=True, help='API 地址 (IP:Port)')
    p_imp.add_argument('--import-dir', default='lib/odmp/',
                       help='Excel 文件所在目录（默认 lib/odmp/）')
    p_imp.add_argument('--mode', default='cover', choices=VALID_MODES,
                       help='导入模式: cover（覆盖，默认）, skip（跳过已存在）')
    p_imp.add_argument('--install-dir', default='/data',
                       help='安装根目录（默认 /data），flexibleJob 导入后自动更新弹性作业 artifacts')

    p_cfg = sub.add_parser('config', help='系统管理配置初始化')
    p_cfg.add_argument('--api', required=True, help='API 地址 (IP:Port)')

    p_upd = sub.add_parser('process', help='数据处理任务配置更新（Kafka/MySQL/CK地址）')
    p_upd.add_argument('--api', required=True, help='API 地址 (IP:Port)')

    p_job = sub.add_parser('job', help='弹性作业配置更新（aimeter-alert Nacos/artifacts）')
    p_job.add_argument('--api', required=True, help='API 地址 (IP:Port)')
    p_job.add_argument('--install-dir', default='/data',
                       help='安装根目录（默认 /data），artifacts 路径为 {dir}/apps/aimeter/{pkg}#app')

    args = parser.parse_args()

    if args.command not in _FLOW_CLASSES:
        parser.print_help()
        sys.exit(1)

    logger = _setup_logger()
    logger.info('ODMP API 工具启动: command=%s api=%s', args.command, args.api)

    if ':' not in args.api:
        logger.error('--api 格式错误，需要包含端口，如 192.168.217.101:9900')
        sys.exit(1)

    cls, desc = _FLOW_CLASSES[args.command]
    flow = cls(args.api)

    try:
        if args.command == 'ingestion':
            flow.run(
                package_dir=args.package_dir,
                list_only=args.list,
                builtin_only=args.builtin_only,
                local_only=args.local_only,
                logger=logger,
            )
        elif args.command == 'import':
            flow.run(import_dir=args.import_dir, mode=args.mode, logger=logger,
                     install_dir=args.install_dir)
        elif args.command == 'config':
            infra = load_config_file()
            zk_connect = None
            deploy = infra.get('deploy', {})
            zk_cfg = infra.get('zookeeper', {})
            if deploy and zk_cfg:
                zk_port = zk_cfg.get('port', 2181)
                zk_hosts = sorted(
                    h for h, comps in deploy.items() if 'zookeeper' in (comps or []))
                if zk_hosts:
                    zk_connect = ','.join('{}:{}'.format(h, zk_port) for h in zk_hosts)
            if not zk_connect:
                logger.info('config.yaml 中无 zookeeper 信息，跳过 ZK 配置')
            flow.run(zk_connect=zk_connect, logger=logger)
        elif args.command == 'process':
            flow.run(logger=logger)
        elif args.command == 'job':
            flow.run(
                install_dir=args.install_dir,
                logger=logger,
            )
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
