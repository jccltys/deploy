#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClickHouse 数据库工具模块 — 供各 installer 复用

支持集群模式，建库时自动附加 ON CLUSTER 子句。
"""
import os
import shlex

from core.ssh_client import get_ssh_client
from core.config_utils import get_clickhouse_vars, get_component_config


def get_clickhouse_cmd(ssh, install_dir):
    code, out, _ = ssh.execute('which clickhouse-client 2>/dev/null')
    if code == 0 and out.strip():
        return out.strip()

    ch_path = os.path.join(install_dir, 'comms', 'clickhouse', 'bin', 'clickhouse-client')
    code, _, _ = ssh.execute('test -x {}'.format(shlex.quote(ch_path)))
    if code == 0:
        return ch_path

    return None


def create_database(ssh, clickhouse_cmd, db_name, cluster_name,
                    host, port, user='default', password='',
                    logger=None):
    if logger:
        logger.info('[%s] 创建 ClickHouse 数据库: %s ON CLUSTER \'%s\'',
                    ssh.host, db_name, cluster_name)

    auth = '--user {}'.format(shlex.quote(user))
    if password:
        auth += ' --password {}'.format(shlex.quote(password))

    sql = "CREATE DATABASE IF NOT EXISTS `{}` ON CLUSTER '{}'".format(
        db_name, cluster_name)

    cmd = (
        '{} --host {} --port {} {} '
        '--query {} 2>&1'
    ).format(
        shlex.quote(clickhouse_cmd),
        shlex.quote(host), port,
        auth,
        shlex.quote(sql),
    )

    code, out, err = ssh.execute(cmd)
    if code != 0:
        raise RuntimeError(
            '[{}] 创建 ClickHouse 数据库 {} 失败: {}'
            .format(ssh.host, db_name, (out or err)[:200]))

    if logger:
        logger.info('[%s] ClickHouse 数据库 %s 创建成功', ssh.host, db_name)


def init_database(ssh, install_dir, db_name, cluster_name,
                  host, port, user='default', password='',
                  logger=None):
    ch_cmd = get_clickhouse_cmd(ssh, install_dir)
    if not ch_cmd:
        raise RuntimeError(
            '[{}] 远程主机未找到 clickhouse-client，'
            '无法初始化 ClickHouse 数据库。'
            .format(ssh.host))

    create_database(ssh, ch_cmd, db_name, cluster_name,
                    host=host, port=port, user=user, password=password,
                    logger=logger)


def create_clickhouse_database(db_name, config, context, logger=None):
    ch_hosts = sorted(getattr(context, 'comp_hosts', {}).get('clickhouse', []))
    if not ch_hosts:
        raise RuntimeError('context 中未配置 clickhouse 主机')

    servers_map = getattr(context, 'servers_map', {})
    target_host = ch_hosts[0]
    server_info = servers_map.get(target_host)
    if not server_info:
        raise RuntimeError('未找到 ClickHouse 主机 {} 的 SSH 配置'.format(target_host))

    ch_vars = get_clickhouse_vars(context, config)
    if not ch_vars:
        raise RuntimeError('未找到 clickhouse 配置')

    cluster = ch_vars.get('clickhouse_cluster', 'ckcluster')
    user = 'default'
    password = ch_vars.get('clickhouse_password', '')
    install_dir = getattr(config, 'install_dir', '/data/service')

    ssh = get_ssh_client(server_info, dry_run=False, logger=logger)
    try:
        init_database(ssh, install_dir, db_name, cluster,
                      host='localhost', port=ch_vars['clickhouse_tcp_port'],
                      user=user, password=password,
                      logger=logger)
    finally:
        ssh.close()
