#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化组件部署平台 — 统一启动入口
解析 CLI 参数 → 加载配置 → 启动 HTTP 服务 → 按组件顺序部署到各主机
"""
import argparse
import os
import re
import sys
import importlib
import logging

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from core.parser import load_config
from core.logger import setup_logger
from core.ssh_client import get_ssh_client
from core.http_server import HTTPServerThread
from core.precheck import precheck_deployment as _precheck
from core.deploy import deploy_component, prepare_all_hosts
from core.config_utils import get_zookeeper_cluster_hosts
from installers.common.base_installer import BaseInstaller, DeployConfig, RuntimeContext
from utils.prepare_hadoop_conf import prepare_hadoop_conf
from utils.health import check_zookeeper_cluster_health


def import_installers():
    """递归扫描 installers/<group>/ 子目录发现所有 *Installer 类并注册

    每个安装器的分组信息从其所在目录路径推断（如 installers/common/ → group='common'）。
    BaseInstaller 自身不会被注册为组件。
    返回 (registry, registry_groups) 元组：
    - registry: dict, component_name → installer_class
    - registry_groups: dict, component_name → group_name (如 'common', 'sso' 等)
    """
    registry = {}
    registry_groups = {}
    installers_root = os.path.join(_SCRIPT_DIR, 'installers')

    for root, dirs, files in os.walk(installers_root):
        if root == installers_root:
            continue
        if '__pycache__' in root:
            continue

        for f in sorted(files):
            if not f.endswith('_installer.py'):
                continue
            if f == 'base_installer.py':
                continue

            rel_dir = os.path.relpath(root, installers_root)
            mod_name = 'installers.{}.{}'.format(rel_dir, f[:-3])

            try:
                mod = importlib.import_module(mod_name)
                for attr in dir(mod):
                    cls = getattr(mod, attr)
                    if (isinstance(cls, type)
                            and attr.endswith('Installer')
                            and attr != 'BaseInstaller'):
                        if issubclass(cls, BaseInstaller) and cls is not BaseInstaller:
                            comp = getattr(cls, 'COMPONENT_NAME', None) or attr.replace('Installer', '').lower()
                            registry[comp] = cls
                            group = getattr(cls, 'GROUP', None) or rel_dir
                            registry_groups[comp] = group
            except Exception as e:
                logging.getLogger(__name__).warning('failed to load %s: %s', mod_name, e)
    return registry, registry_groups


# 核心组件安装顺序（java 最先，java11/java21 等额外版本最后安装）
# 核心之后部署其他通用组件（按字母序，如 nginx、elasticsearch 等）
DEFAULT_INSTALL_ORDER = ['java', 'mysql', 'redis', 'zookeeper', 'kafka', 'hadoop', 'nacos', 'ckman', 'clickhouse', 'nebula', 'nebula_studio']

# 自定义组件的固定安装顺序（排在其他通用组件之后）
CUSTOM_INSTALL_ORDER = ['sso', 'odmp', 'dolphinscheduler', 'jax-pyenv', 'datax', 'refiner', 'aimeter', 'odc']


def parse_args():
    p = argparse.ArgumentParser(description='自动化组件部署平台')
    p.add_argument('--localaddr', required=True,help='部署机 IP（远程主机通过此地址下载安装包）')
    p.add_argument('--nodesfile', required=True,help='节点配置文件路径（YAML）')
    p.add_argument('--install-dir',help='安装根目录（CLI 模式必需；Web 模式可在页面中配置）')
    p.add_argument('--package-dir', help='部署机安装包目录（CLI 模式必需；Web 模式可在页面中配置，默认 {install_dir}/pkgs）')
    p.add_argument('--config-dir',help='配置模板目录（默认 {脚本目录}/conf/template/）')
    p.add_argument('--http-port', type=int, default=8000,help='HTTP 文件服务端口（默认 8000）')
    p.add_argument('--service',help='只部署指定服务（逗号分隔，如 redis,kafka）')
    p.add_argument('--debug', action='store_true',help='调试模式：仅打印安装步骤，不实际执行（含安装包删除步骤的日志）')
    p.add_argument('--fail-fast', action='store_true', default=True,
                   help='任意主机安装失败时终止后续部署（默认启用）')
    p.add_argument('--no-fail-fast', action='store_false', dest='fail_fast',
                   help='禁用 fail-fast，安装失败后继续部署其他组件')
    p.add_argument('--json-log', action='store_true',help='以 JSON 格式输出日志')
    p.add_argument('--web', action='store_true', help='启动 Web 管理模式（替代 CLI 部署流程）')
    p.add_argument('--web-port', type=int, default=18080, help='Web 服务端口（默认 18080）')
    return p.parse_args()


def precheck_deployment(comp_hosts, servers_map, config, context, logger):
    """部署前预检查：委托 core.precheck 模块执行"""
    _precheck(comp_hosts, servers_map, config, context, logger, get_ssh_client)


def validate_args(args, logger):
    """校验参数合法性，不合法则记录错误并退出"""
    ip_pattern = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    if not ip_pattern.match(args.localaddr):
        logger.error('--localaddr "%s" 不是有效的 IPv4 地址', args.localaddr)
        sys.exit(1)

    if not os.path.isfile(args.nodesfile):
        logger.error('--nodesfile "%s" 文件不存在', args.nodesfile)
        sys.exit(1)


def main():
    args = parse_args()

    # Web 管理模式：跳过 CLI 校验和部署流程，直接启动 Web 服务
    if args.web:
        deploy_log_dir = os.path.join(_SCRIPT_DIR, 'logs')
        logger = setup_logger(deploy_log_dir, debug=args.debug, json_log=args.json_log)
        if not os.path.isfile(args.nodesfile):
            logger.error('--nodesfile "%s" 文件不存在，Web 模式需要有效的 config.yaml 路径', args.nodesfile)
            sys.exit(1)
        logger.info('=== 启动 Web 管理模式 ===')
        logger.info('配置文件: %s', args.nodesfile)
        logger.info('Web 服务端口: %d', args.web_port)
        from web.main import start_web
        start_web(host=args.localaddr, port=args.web_port, config_path=args.nodesfile)
        return

    # CLI 模式：install-dir 为必需
    if not args.install_dir:
        print('错误: --install-dir 是必需参数（CLI 部署模式）', file=sys.stderr)
        sys.exit(1)

    # 尽早初始化日志，使 validate_args 中可以记录错误
    deploy_log_dir = os.path.join(_SCRIPT_DIR, 'logs')
    logger = setup_logger(deploy_log_dir, debug=args.debug, json_log=args.json_log)

    validate_args(args, logger)

    # 解析路径参数
    install_dir = os.path.abspath(args.install_dir)
    package_dir = os.path.abspath(args.package_dir) if args.package_dir else os.path.join(install_dir, 'pkgs')
    config_dir = os.path.abspath(args.config_dir) if args.config_dir else os.path.join(_SCRIPT_DIR, 'conf', 'template')

    # 加载 YAML 配置
    cfg, servers_map, deploy_map = load_config(args.nodesfile)

    # 创建只读配置（DeployConfig）和可变运行时上下文（RuntimeContext）
    config = DeployConfig(
        install_dir=install_dir,
        package_dir=package_dir,
        config_template_dir=config_dir,
        http_port=args.http_port,
        comms_dir=os.path.join(install_dir, 'comms'),
        apps_dir=os.path.join(install_dir, 'apps'),
        debug=args.debug,
        fail_fast=args.fail_fast,
        packages=cfg.get('packages', {}),
        host_ip=args.localaddr,
        deploy_log_dir=deploy_log_dir,
        mysql_password=cfg.get('mysql', {}).get('password', 'MySQL@123'),
        mysql_user=cfg.get('mysql', {}).get('user', 'root'),
        java_env=cfg.get('java_env', {}),
        nacos_password=cfg.get('nacos', {}).get('password', '0192023A7BBD73250516F069DF18B500'),
        raw_config=cfg,
    )
    context = RuntimeContext()
    context.servers_map = servers_map

    logger.info('=== 部署开始 ===')
    logger.info('配置文件: %s', args.nodesfile)
    logger.info('安装根目录: %s', install_dir)
    logger.info('安装包目录: %s', package_dir)
    logger.info('配置模板目录: %s', config_dir)
    logger.info('远程 comms 目录: %s', config.comms_dir)
    logger.info('HTTP 端口: %d', config.http_port)
    logger.info('fail-fast 模式: %s', '启用' if config.fail_fast else '禁用')
    logger.info('本机 IP: %s', config.host_ip)
    if args.debug:
        logger.info('调试模式: 仅打印步骤，不实际执行')

    # 安装本地 Python 依赖（deploy/lib/python/*.tar.gz）
    lib_python_dir = os.path.join(_SCRIPT_DIR, 'lib', 'python')
    if os.path.isdir(lib_python_dir):
        for fname in sorted(os.listdir(lib_python_dir)):
            if not fname.endswith('.tar.gz'):
                continue
            pkg_path = os.path.join(lib_python_dir, fname)
            logger.info('正在安装 Python 依赖: %s', fname)
            extract_dir = os.path.join(lib_python_dir, fname.replace('.tar.gz', ''))
            try:
                import tarfile
                with tarfile.open(pkg_path, 'r:gz') as tar:
                    tar.extractall(path=lib_python_dir)
                setup_dir = extract_dir
                if not os.path.isfile(os.path.join(setup_dir, 'setup.py')):
                    # tar 可能包了一层目录名不同的目录
                    inner = [d for d in os.listdir(extract_dir)
                             if os.path.isfile(os.path.join(extract_dir, d, 'setup.py'))]
                    if inner:
                        setup_dir = os.path.join(extract_dir, inner[0])
                if os.path.isfile(os.path.join(setup_dir, 'setup.py')):
                    import subprocess
                    subprocess.check_call(
                        [sys.executable, 'setup.py', 'install'],
                        cwd=setup_dir)
                    import shutil
                    if os.path.isdir(extract_dir):
                        shutil.rmtree(extract_dir, ignore_errors=True)
                    logger.info('Python 依赖安装完成: %s', fname)
            except Exception as e:
                logger.warning('Python 依赖安装失败: %s - %s', fname, e)

    # 启动 HTTP 文件服务（提供安装包下载）
    try:
        httpd = HTTPServerThread(config.package_dir, config.http_port)
        httpd.start()
        logger.info('HTTP 文件服务已启动，端口 %d', config.http_port)
    except Exception as e:
        logger.error('HTTP 文件服务启动失败: %s', e)
        sys.exit(1)

    # 发现并注册安装器
    registry, registry_groups = import_installers()
    logger.info('已注册的安装器: %s', ', '.join(sorted(registry)))

    # 从已注册安装器中自动检测额外 Java 版本（java11 / java21 等）
    # 只要有对应的安装器，默认安装到所有主机，无需在 deploy 中显式声明
    registered_java_versions = sorted(
        c for c in registry if c.startswith('java') and c != 'java'
    )
    if registered_java_versions:
        logger.info('检测到额外 Java 版本: %s', ', '.join(registered_java_versions))

    # 自动为每台主机添加所有 Java 版本（默认 java + 额外 java11/java21 等）
    for host, comps in deploy_map.items():
        if 'java' not in comps:
            comps.insert(0, 'java')
        for java_ver in registered_java_versions:
            if java_ver not in comps:
                comps.insert(1, java_ver)

    _AUTO_DEPLOY_WITH_DEPENDENCY = {
        'jax-pyenv': 'odmp',
        'datax': 'dolphinscheduler',
    }
    for auto_comp, dep_comp in _AUTO_DEPLOY_WITH_DEPENDENCY.items():
        if auto_comp not in registry:
            continue
        for host, comps in deploy_map.items():
            if dep_comp in comps and auto_comp not in comps:
                logger.info('自动添加 %s 到主机 %s（与 %s 一致）', auto_comp, host, dep_comp)
                comps.append(auto_comp)

    # 建立组件 → 主机列表的映射
    comp_hosts = {}
    for host, comps in deploy_map.items():
        for comp in comps:
            comp_hosts.setdefault(comp, []).append(host)
    context.comp_hosts = comp_hosts

    # 新安装顺序：java + extra_java + DEFAULT_ORDER剩余 + other_common + CUSTOM_ORDER + other_custom
    all_components = set()
    for comps in deploy_map.values():
        for c in comps:
            all_components.add(c)
    extra_java = {c for c in all_components if c.startswith('java') and c != 'java'}
    core_order = ['java'] + sorted(extra_java) + [c for c in DEFAULT_INSTALL_ORDER if c != 'java']
    other_common = sorted([c for c in all_components if registry_groups.get(c) == 'common' and c not in core_order and c not in extra_java])
    fixed_custom = [c for c in CUSTOM_INSTALL_ORDER if c in all_components]
    other_custom = sorted([c for c in all_components if c not in core_order and c not in other_common and c not in fixed_custom])
    install_order = core_order + other_common + fixed_custom + other_custom

    if args.service:
        services = [s.strip().lower().replace('-', '_') for s in args.service.split(',')]
        install_order = [s for s in install_order if s.replace('-', '_') in services]
        logger.info('服务过滤: 只部署 %s', ', '.join(services))
    else:
        logger.info('安装顺序: %s', ' → '.join(install_order))

    precheck_deployment(comp_hosts, servers_map, config, context, logger)

    _prepare_mockdata_config(config, context, logger)

    # 预先在所有主机上创建公共目录
    prepare_all_hosts(deploy_map, servers_map, config, context, logger)

    # 按组件顺序部署（同组件跨主机并行，组件间串行）
    results = {}
    zk_checked = False
    for comp in install_order:
        installer_cls = registry.get(comp)

        if getattr(installer_cls, 'REQUIRES_ZK_CHECK', False) and not zk_checked:
            zk_hosts = get_zookeeper_cluster_hosts(context.comp_hosts)
            if zk_hosts:
                if config.debug:
                    logger.info('调试模式：跳过 ZooKeeper 集群健康检查')
                else:
                    logger.info('--- 开始 ZooKeeper 集群健康检查 ---')
                    check_zookeeper_cluster_health(zk_hosts, config.install_dir, config, servers_map, logger)
                    logger.info('--- ZooKeeper 集群健康检查通过 ---')
            else:
                logger.warning('未配置 ZooKeeper 主机，跳过 ZK 健康检查')
            zk_checked = True

        hosts = comp_hosts.get(comp, [])
        if not hosts:
            logger.warning('没有主机配置了组件: %s', comp)
            continue
                # 部署 odmp / dolphinscheduler 前先准备 Hadoop 配置文件
        if getattr(installer_cls, 'REQUIRES_HADOOP_CONF', False):
            prepare_hadoop_conf(comp_hosts, servers_map, config.package_dir,
                                config.install_dir, logger)

        deploy_component(comp, hosts, registry, servers_map, config, context, logger, results)

        # 检查当前组件是否有失败主机
        failed_hosts = [h for h, s in results.get(comp, {}).items() if s == 'failed']
        if failed_hosts and config.fail_fast:
            logger.error('===== 组件安装失败 =====')
            for c, host_results in results.items():
                failed = [h for h, s in host_results.items() if s == 'failed']
                if failed:
                    logger.error('  %s: 失败主机 %s', c, ', '.join(failed))
            logger.error('本地日志: %s', config.deploy_log_dir)
            logger.error('远程日志: %s/%s', config.install_dir, 'comms')
            logger.error('部署已中止。使用 --no-fail-fast 继续部署其他组件。')
            sys.exit(1)

    httpd.stop()

    # 打印部署结果汇总
    logger.info('=== 部署结果汇总 ===')
    all_ok = True
    for comp, host_results in sorted(results.items()):
        ok = sum(1 for s in host_results.values() if s == 'success')
        fail = sum(1 for s in host_results.values() if s == 'failed')
        if fail:
            all_ok = False
        logger.info('  %s: %d 成功, %d 失败', comp, ok, fail)
    if all_ok:
        logger.info('=== 所有组件部署成功 ===')
    else:
        logger.warning('=== 部分组件部署失败，请检查日志 ===')

    # 降级汇总：提示无 sudo 权限的主机（服务以脚本直启、未纳入 systemd）
    none_hosts = [h for h, m in getattr(context, 'sudo_mode', {}).items() if m == 'none']
    if none_hosts:
        logger.warning('=== 以下主机无 sudo 权限，服务已脚本直启（未纳入 systemd / 未开机自启）===')
        for h in sorted(none_hosts):
            logger.warning('  %s', h)
        logger.warning('  待有 root 权限后，可将 %s/systemd/*.service 复制到 /etc/systemd/system/ 并 systemctl enable --now 启用。',
                       config.install_dir)


def _prepare_mockdata_config(config, context, logger):
    """从 config.yaml 推断 MySQL 和 Kafka 地址，写入 mockdata/config/common_config.yaml

    MySQL host → comp_hosts['mysql'] 中第一台主机
    Kafka brokers → comp_hosts['kafka'] 中所有主机 + kafka.port
    端口/用户/密码 → config.yaml 中各组件配置段
    """
    comp_hosts = getattr(context, 'comp_hosts', {}) or {}
    mysql_hosts = comp_hosts.get('mysql', [])
    kafka_hosts = comp_hosts.get('kafka', [])
    raw = getattr(config, 'raw_config', {}) or {}

    if not mysql_hosts and not kafka_hosts:
        logger.info('未部署 MySQL 和 Kafka，跳过 mockdata 配置生成')
        return

    mockdata_dir = os.path.join(_SCRIPT_DIR, 'mockdata', 'config')
    os.makedirs(mockdata_dir, exist_ok=True)

    mysql_cfg = raw.get('mysql', {})
    mysql_port = mysql_cfg.get('port', 3306)
    mysql_user = getattr(config, 'mysql_user', 'root') or 'root'
    mysql_password = getattr(config, 'mysql_password', 'MySQL@123') or 'MySQL@123'
    mysql_host = mysql_hosts[0] if mysql_hosts else '127.0.0.1'

    kafka_cfg = raw.get('kafka', {})
    kafka_port = kafka_cfg.get('port', 9092)
    if kafka_hosts:
        kafka_brokers = ','.join(
            '{}:{}'.format(h, kafka_port) for h in sorted(kafka_hosts)
        )
    else:
        kafka_brokers = '127.0.0.1:{}'.format(kafka_port)

    content = (
        '# 公共基础设施配置文件（由 install.py 自动生成，请勿手动修改）\n'
        '# 仅配置 MySQL/Kafka 基础设施地址，topic 名称使用 config_loader.py 中的内置默认值\n'
        '\n'
        'mysql:\n'
        '  host: {}\n'
        '  port: {}\n'
        '  user: {}\n'
        '  password: "{}"\n'
        '\n'
        'kafka:\n'
        '  brokers: "{}"\n'
    ).format(mysql_host, mysql_port, mysql_user, mysql_password, kafka_brokers)

    yaml_path = os.path.join(mockdata_dir, 'common_config.yaml')
    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info('mockdata 基础设施配置已自动生成: %s', yaml_path)
        logger.info('  MySQL: %s:%s', mysql_host, mysql_port)
        logger.info('  Kafka brokers: %s', kafka_brokers)
    except Exception as e:
        logger.warning('写入 mockdata 配置失败: %s', e)


if __name__ == '__main__':
    main()
