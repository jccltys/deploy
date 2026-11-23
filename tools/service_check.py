#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组件健康巡检脚本 — 对已部署的组件执行健康检查

复用 utils/health 中的检查器，不依赖安装器实例。
日志同时输出到控制台和 deploy/logs/service_check.log。

用法:
  python3 -m deploy.tools.service_check --nodesfile deploy/config.yaml --install-dir /data/service --service redis
  python3 -m deploy.tools.service_check --nodesfile deploy/config.yaml --install-dir /data/service --debug
"""
import argparse
import datetime
import logging
import os
import re
import shlex
import sys
from logging.handlers import RotatingFileHandler

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, 'deploy'))

from core.parser import load_config
from core.ssh_client import SSHClient
from installers.common.base_installer import DeployConfig, RuntimeContext
from utils.health import (
    RedisChecker, RedisSentinelChecker, NginxChecker, ZookeeperChecker, KafkaChecker,
    MySQLChecker, HadoopChecker, CkmanChecker, JavaChecker, NacosChecker,
    ClickHouseChecker, NebulaChecker, NebulaStudioChecker, SsoChecker, OdmpChecker,
    RefinerProChecker, RefinerEtlChecker, AimeterAlertChecker, AimeterSchedulerChecker,
    DolphinschedulerChecker,
)
from core.config_utils import get_component_config

CHECKER_REGISTRY = {
    'redis': RedisChecker,
    'redis-sentinel': RedisSentinelChecker,
    'nginx': NginxChecker,
    'zookeeper': ZookeeperChecker,
    'kafka': KafkaChecker,
    'mysql': MySQLChecker,
    'hadoop': HadoopChecker,
    'ckman': CkmanChecker,
    'java': JavaChecker,
    'java11': JavaChecker,
    'java21': JavaChecker,
    'nacos': NacosChecker,
    'clickhouse': ClickHouseChecker,
    'nebula': NebulaChecker,
    'nebula_studio': NebulaStudioChecker,
    'sso': SsoChecker,
    'odmp': OdmpChecker,
    'refiner-pro': RefinerProChecker,
    'refiner-pro-etl': RefinerEtlChecker,
    'aimeter': AimeterAlertChecker,
    'aimeter-scheduler': AimeterSchedulerChecker,
    'dolphinscheduler': DolphinschedulerChecker,
}

# 组件展开映射：父组件名 → 子服务列表（巡检时分别输出一行）
SUB_COMPONENTS = {
    'refiner': ['refiner-pro', 'refiner-pro-etl'],
    'aimeter': ['aimeter', 'aimeter-scheduler'],
}


def setup_logger(log_dir, debug=False):
    """初始化日志器，同时输出到文件（轮转）和控制台"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'service_check.log')
    logger = logging.getLogger('service_check')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

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


def parse_args():
    p = argparse.ArgumentParser(description='组件健康巡检工具')
    p.add_argument('--nodesfile', help='节点配置文件路径（YAML，--status 时可选）')
    p.add_argument('--install-dir', help='安装根目录（--status 时可选）')
    p.add_argument('--service', help='只巡检指定服务（逗号分隔，如 redis,kafka）')
    p.add_argument('--debug', action='store_true', help='调试模式：仅打印步骤，不实际执行')
    p.add_argument('--status', action='store_true', help='查看最近一次监控状态记录（不重新巡检）')
    return p.parse_args()


def get_ssh_client(server_info, dry_run=False, logger=None):
    return SSHClient(
        host=server_info['host'],
        port=server_info.get('port', 22),
        username=server_info.get('username', 'root'),
        key_file=server_info.get('key_file'),
        dry_run=dry_run,
        logger=logger,
    )


def inspect_component(host, component, config, context, dry_run=False, logger=None):
    """在指定主机上检查指定组件的健康状态"""
    servers_map = getattr(context, 'servers_map', {}) or {}
    server_info = servers_map.get(host)
    if not server_info:
        return 'skipped', '未找到 SSH 配置'

    checker_cls = CHECKER_REGISTRY.get(component)
    if not checker_cls:
        return 'skipped', '无对应的检查器'

    ssh = get_ssh_client(server_info, dry_run=dry_run, logger=logger)
    component_dir = os.path.join(config.comms_dir, component)

    try:
        kwargs = {}
        if component == 'mysql':
            kwargs['password'] = getattr(config, 'mysql_password', 'MySQL@123')
        if component == 'redis':
            redis_cfg = get_component_config(config, 'redis')
            kwargs['password'] = redis_cfg.get('password', 'Redis@123')
        if component == 'clickhouse':
            kwargs['context'] = context
        if component == 'sso':
            kwargs['context'] = context
            component_dir = os.path.join(config.apps_dir, component)
        if component == 'odmp':
            kwargs['context'] = context
            component_dir = os.path.join(config.apps_dir, component)
        if component in ('refiner-pro', 'refiner-pro-etl'):
            kwargs['context'] = context
            component_dir = os.path.join(config.apps_dir, 'refiner')
        if component in ('aimeter', 'aimeter-scheduler'):
            kwargs['context'] = context
            component_dir = os.path.join(config.apps_dir, 'aimeter')
        if component == 'dolphinscheduler':
            kwargs['context'] = context
            component_dir = os.path.join(config.apps_dir, 'odmp', component)

        checker = checker_cls(ssh, component_dir, config, logger, **kwargs)
        checker.check()

        if component == 'redis':
            redis_hosts = sorted(getattr(context, 'comp_hosts', {}).get('redis', []))
            if len(redis_hosts) == 3:
                RedisSentinelChecker(ssh, component_dir, config, logger).check()

        return 'healthy', ''
    except Exception as e:
        return 'unhealthy', str(e)
    finally:
        ssh.close()


def _log_result(logger, host, comp, status, detail, dry_run):
    status_line = '[{}] {}/{}: {}'.format(status.upper(), host, comp, status)
    if detail:
        status_line += ' ({})'.format(detail)
    if dry_run:
        status_line = '[DRYRUN] {}'.format(status_line)
        logger.info(status_line)
    elif status == 'healthy':
        logger.info(status_line)
    elif status == 'unhealthy':
        logger.error(status_line)
    else:
        logger.warning(status_line)


def _show_status(logger):
    """读取并显示最近一次监控状态记录"""
    md_path = os.path.join(_SCRIPT_DIR, 'deploy', 'docs', 'service-status.md')
    if not os.path.isfile(md_path):
        logger.warning('暂无监控状态记录，请先运行巡检 (service_check.py 不带 --status)')
        return 0

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    logger.info('=' * 60)
    logger.info('最近监控状态记录')
    logger.info('=' * 60)
    # 取最后一条记录（文件末尾追加）
    sections = content.split('\n## ')
    if len(sections) > 1:
        last = sections[-1].strip()
        logger.info('\n## ' + last)
    else:
        logger.info(content)
    logger.info('=' * 60)
    logger.info('完整记录: %s', md_path)
    return 0


def main():
    args = parse_args()
    logger = setup_logger(os.path.join(_SCRIPT_DIR, 'deploy', 'logs'), debug=args.debug)

    if args.status:
        return _show_status(logger)

    missing = []
    if not args.nodesfile:
        missing.append('--nodesfile')
    if not args.install_dir:
        missing.append('--install-dir')
    if missing:
        sys.exit('错误: {} 是必填参数（--status 模式除外）'.format('、'.join(missing)))

    cfg, servers_map, deploy_map = load_config(args.nodesfile)

    install_dir = os.path.abspath(args.install_dir)
    config_template_dir = os.path.join(_SCRIPT_DIR, 'deploy', 'conf', 'template')
    config = DeployConfig(
        install_dir=install_dir,
        package_dir='',
        config_template_dir=config_template_dir,
        http_port=8000,
        comms_dir=os.path.join(install_dir, 'comms'),
        apps_dir=os.path.join(install_dir, 'apps'),
        debug=args.debug,
        fail_fast=False,
        packages=cfg.get('packages', {}),
        host_ip='127.0.0.1',
        deploy_log_dir='',
        mysql_password=cfg.get('mysql', {}).get('password', 'MySQL@123'),
        mysql_user=cfg.get('mysql', {}).get('user', 'root'),
        java_env=cfg.get('java_env', {}),
        nacos_password=cfg.get('nacos', {}).get('password', '0192023A7BBD73250516F069DF18B500'),
        raw_config=cfg,
    )
    context = RuntimeContext()
    context.servers_map = servers_map

    comp_hosts = {}
    for host, comps in deploy_map.items():
        for c in comps:
            comp_hosts.setdefault(c, []).append(host)
    context.comp_hosts = comp_hosts

    dry_run = args.debug

    if args.service:
        services = [s.strip().lower().replace('-', '_') for s in args.service.split(',')]
    else:
        services = None

    log_dir = os.path.join(_SCRIPT_DIR, 'deploy', 'logs')
    logger = setup_logger(log_dir, debug=dry_run)

    logger.info('=' * 60)
    logger.info('组件健康巡检')
    logger.info('=' * 60)
    if dry_run:
        logger.info('调试模式：仅打印步骤，不实际执行')

    all_healthy = True
    summary = []

    # 扩展 --service 过滤：--service refiner 自动匹配 refiner-pro/refiner-pro-etl
    if services:
        expanded_services = set()
        for s in services:
            if s in SUB_COMPONENTS:
                expanded_services.update(SUB_COMPONENTS[s])
            else:
                expanded_services.add(s)
        services = expanded_services

    # 按组件分组：comp -> [hosts]
    comp_hosts = {}
    all_hosts = set()
    for host, comps in deploy_map.items():
        all_hosts.add(host)
        for c in comps:
            if services and c not in services:
                continue
            if c not in CHECKER_REGISTRY and c not in SUB_COMPONENTS:
                continue
            comp_hosts.setdefault(c, []).append(host)

    # 展开子组件：refiner → refiner-pro + refiner-pro-etl
    expanded = {}
    for comp, hosts in comp_hosts.items():
        if comp in SUB_COMPONENTS:
            for sub in SUB_COMPONENTS[comp]:
                expanded[sub] = hosts
        else:
            expanded[comp] = hosts
    comp_hosts = expanded

    # 自动安装的组件（java/java11/java21）补充到所有主机
    for name in ('java', 'java11', 'java21'):
        if name not in comp_hosts and all_hosts:
            if not services or name in services:
                comp_hosts[name] = sorted(all_hosts)

    # 按组件顺序巡检（同组件跨主机并行）
    for comp in sorted(comp_hosts.keys()):
        hosts = comp_hosts[comp]
        logger.info('--- 检查组件: %s (主机: %s) ---', comp, ', '.join(sorted(hosts)))

        # ── dolphinscheduler: status-all.sh 跑一次输出所有节点状态 ──
        if comp == 'dolphinscheduler':
            first_host = sorted(hosts)[0]
            servers_map = getattr(context, 'servers_map', {}) or {}
            server_info = servers_map.get(first_host)
            if not server_info:
                for h in sorted(hosts):
                    summary.append((h, comp, 'skipped', '未找到 SSH 配置'))
                continue

            ssh = get_ssh_client(server_info, dry_run=dry_run, logger=logger)
            component_dir = os.path.join(config.apps_dir, 'odmp', comp)
            status_sh = os.path.join(component_dir, 'bin', 'status-all.sh')
            code, out, err = ssh.execute('bash {} 2>&1'.format(shlex.quote(status_sh)),
                                         timeout=30, check=False)
            ssh.close()

            # 解析每台主机的服务状态
            # 先剥离 ANSI 转义码（如 \033[32m, \033[0m），否则它们会被误认为状态标记
            _ansi_re = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
            clean_lines = [_ansi_re.sub('', l) for l in out.split('\n')]

            if dry_run or logger.isEnabledFor(logging.DEBUG):
                logger.debug('status-all.sh 原始输出 (已剥离 ANSI):\n%s', '\n'.join(clean_lines))

            host_services = {}
            current_ip = None
            for raw in clean_lines:
                line = raw.strip()
                # 匹配 "Begin status" 行，提取 IP
                m = re.match(r'^(\d+\.\d+\.\d+\.\d+)\s+Begin\s+status\s+(.+)', line)
                if m:
                    current_ip = m.group(1)
                    host_services.setdefault(current_ip, [])
                    continue
                # 匹配服务状态行:  "xxx  [ RUNNING ]" 或 "xxx  [ STOP ]"
                if current_ip and re.search(r'\[\s*(RUNNING|STOP|NOT\s+RUNNING)\s*\]', line):
                    parts = line.split('[')
                    svc = parts[0].strip()
                    st = re.search(r'\[\s*(\w+(?:\s+\w+)?)\s*\]', line).group(1)
                    if svc and st:
                        host_services[current_ip].append((svc, st))

            # 方案2: 从配置头 hosts:[...] 提取所有 IP（如果方案1没解析到）
            if not host_services:
                for line in out.split('\n'):
                    m = re.search(r'hosts:\[\s*([^\]]+)\]', line)
                    if m:
                        for item in m.group(1).split(','):
                            ip = item.strip().split(':')[0]
                            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                                host_services.setdefault(ip, [])

            for host in sorted(hosts):
                services = host_services.get(host)
                if services is None:
                    status, detail = 'skipped', '未在 status-all.sh 输出中找到'
                elif code != 0:
                    status, detail = 'unhealthy', 'status-all.sh 返回码: {}'.format(code)
                else:
                    stopped = [(s, st) for s, st in services if st != 'RUNNING']
                    if stopped:
                        detail = '; '.join('{} [{}]'.format(s, st) for s, st in stopped)
                        status = 'unhealthy'
                    else:
                        status, detail = 'healthy', ''

                _log_result(logger, host, comp, status, detail, dry_run)
                summary.append((host, comp, status, detail))
                if status == 'unhealthy':
                    all_healthy = False
            continue

        # ── 普通组件：逐主机检查 ──
        for host in sorted(hosts):
            status, detail = inspect_component(host, comp, config, context, dry_run=dry_run, logger=logger)
            _log_result(logger, host, comp, status, detail, dry_run)

            summary.append((host, comp, status, detail))
            if status == 'unhealthy':
                all_healthy = False

    logger.info('=' * 60)
    summary_ok = sum(1 for _, _, s, _ in summary if s == 'healthy')
    summary_skip = sum(1 for _, _, s, _ in summary if s == 'skipped')
    summary_fail = sum(1 for _, _, s, _ in summary if s == 'unhealthy')
    logger.info('巡检结果汇总: %d 健康, %d 跳过, %d 异常',
                summary_ok, summary_skip, summary_fail)

    logger.info('按组件分布的详细状态:')
    for comp in sorted(comp_hosts.keys()):
        comp_items = [item for item in summary if item[1] == comp]
        ok = sum(1 for _, _, s, _ in comp_items if s == 'healthy')
        fail = sum(1 for _, _, s, _ in comp_items if s == 'unhealthy')
        status_comp = 'healthy' if fail == 0 else 'unhealthy'
        logger.info('  %s: %d/%d 健康, %d/%d 异常 [%s]',
                    comp, ok, len(comp_items), fail, len(comp_items), status_comp)

    if summary_fail > 0:
        logger.info('异常服务:')
        for host, comp, status, detail in summary:
            if status == 'unhealthy':
                reason = ' ({})'.format(detail) if detail else ''
                logger.info('  %s/%s: %s%s', host, comp, status, reason)
    if all_healthy:
        logger.info('所有组件健康检查通过')
    else:
        logger.warning('存在异常组件，请检查')
    logger.info('=' * 60)

    _write_status_md(summary, comp_hosts)

    return 0 if all_healthy else 1


def _write_status_md(summary, comp_hosts):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    docs_dir = os.path.join(_SCRIPT_DIR, 'deploy', 'docs')
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
    md_path = os.path.join(docs_dir, 'service-status.md')

    def _display_width(s):
        """计算字符串的显示宽度（中文字符占2个宽度，英文字符占1个）"""
        w = 0
        for ch in str(s):
            if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
                w += 2
            else:
                w += 1
        return w

    def _md_table(header, rows):
        widths = [_display_width(h) for h in header]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], _display_width(str(cell)))
        pad = lambda s, w: s + ' ' * (w - _display_width(str(s)))
        result = []
        result.append('| ' + ' | '.join(pad(h, widths[i]) for i, h in enumerate(header)) + ' |')
        result.append('| ' + ' | '.join('-' * widths[i] for i in range(len(header))) + ' |')
        for row in rows:
            result.append('| ' + ' | '.join(pad(cell, widths[i]) for i, cell in enumerate(row)) + ' |')
        return result

    lines = []
    if not os.path.exists(md_path):
        lines.append('# 服务监控状态')
        lines.append('')
        lines.append('> 本文件由 `service_check.py` 自动生成，每次巡检后追加记录。')
        lines.append('')

    lines.append('## {}'.format(now))
    lines.append('')

    summary_rows = []
    for comp in sorted(comp_hosts.keys()):
        comp_items = [item for item in summary if item[1] == comp]
        ok = sum(1 for _, _, s, _ in comp_items if s == 'healthy')
        fail = sum(1 for _, _, s, _ in comp_items if s == 'unhealthy')
        status_comp = 'healthy' if fail == 0 else 'unhealthy'
        summary_rows.append([comp, str(len(comp_items)), str(ok), str(fail), status_comp])
    lines.extend(_md_table(['组件', '主机数', '健康', '异常', '状态'], summary_rows))
    lines.append('')

    detail_rows = []
    for host, comp, status, detail in summary:
        detail_show = detail if detail else '-'
        detail_rows.append([comp, host, status, detail_show])
    lines.extend(_md_table(['组件', '主机', '状态', '详情'], detail_rows))
    lines.append('')

    unhealthy_items = [(h, c, d) for h, c, s, d in summary if s == 'unhealthy']
    if unhealthy_items:
        lines.append('### 异常详情')
        lines.append('')
        for host, comp, detail in unhealthy_items:
            lines.append('- **{}@{}**: {}'.format(comp, host, detail))
        lines.append('')

    lines.append('---')
    lines.append('')

    with open(md_path, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logging.getLogger(__name__).info('监控状态已记录到: %s', md_path)


if __name__ == '__main__':
    sys.exit(main())
