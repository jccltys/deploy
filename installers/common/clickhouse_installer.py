# -*- coding: utf-8 -*-
"""ClickHouse 部署安装器 — 通过 ckman API 部署"""
import glob
import os
import shlex
import threading

from core.ckman_api import (ckman_login, ckman_upload_package,
                            ckman_deploy_clickhouse)
from core.health_check import run_health_checks
from core.clickhouse_db import create_clickhouse_database
from utils.health import ClickHouseChecker
from core.ssh_client import get_ssh_client
from installers.common.base_installer import BaseInstaller
from core.config_utils import get_component_config


class ClickHouseInstaller(BaseInstaller):
    GROUP = 'common'
    DEPLOY_MODE = 'cluster'

    @classmethod
    def deploy_cluster(cls, hosts, servers_map, config, context, logger, results):
        """ClickHouse 集群部署入口：通过 ckman API，一台发起、ckman 分发到全集群"""
        ch_hosts = sorted(hosts)
        results.setdefault('clickhouse', {})
        lock = threading.Lock()

        deploy_host = ch_hosts[0]
        logger.info('--- ClickHouse 部署，通过 ckman API，目标主机: %s ---',
                    ', '.join(ch_hosts))

        def _get_ssh(h):
            server_info = servers_map.get(h)
            if not server_info:
                logger.error('未找到主机 %s 的 SSH 配置', h)
                results['clickhouse'][h] = 'skipped'
                return None
            return get_ssh_client(server_info, dry_run=config.debug, logger=logger)

        ssh = _get_ssh(deploy_host)
        if not ssh:
            return

        _instances = {}
        try:
            inst = cls(ssh, config, context, logger)
            inst.install(skip_health_check=True)
            for h in ch_hosts:
                _instances[h] = inst
                results['clickhouse'][h] = 'started'
        except Exception as e:
            logger.error('[%s] ClickHouse 部署失败: %s', deploy_host, e)
            for h in ch_hosts:
                results['clickhouse'][h] = 'failed'
            ssh.close()
            return

        run_health_checks(ch_hosts, _instances, results, 'clickhouse', lock,
                          config, logger, max_retries=6, retry_interval=180,
                          post_start_delay_seconds=180)

        ssh.close()

        failed = [h for h, s in results['clickhouse'].items() if s == 'failed']
        if failed:
            logger.warning('--- ClickHouse 部署失败: %s ---', ', '.join(failed))
        else:
            logger.info('--- ClickHouse 部署完毕（%d 台主机）---', len(ch_hosts))
            # 后置初始化：创建业务数据库
            try:
                for db_name in ('aimeter', 'odmp'):
                    create_clickhouse_database(db_name, config, context, logger=logger)
            except Exception as e:
                logger.warning('[clickhouse] 创建数据库异常: %s（可后续手动创建）', e)

    def _get_ckman_host(self):
        hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('ckman', []))
        if not hosts:
            raise RuntimeError('未找到 ckman 主机，无法部署 ClickHouse')
        return hosts[0]

    def _get_clickhouse_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('clickhouse', []))

    def _get_clickhouse_config(self):
        cfg = get_component_config(self.config, 'clickhouse')
        return {
            'tcp_port': cfg.get('tcp_port', 19000),
            'http_port': cfg.get('http_port', 18123),
            'keeper_tcp_port': cfg.get('keeper_tcp_port', 9181),
            'keeper_raft_port': cfg.get('keeper_raft_port', 9234),
            'password': cfg.get('password', 'ck@123'),
            'path': cfg.get('path', '/data/clickhouse/'),
            'ssh_user': cfg.get('ssh_user', 'root'),
            'ssh_port': cfg.get('ssh_port', 22),
            'authenticate_type': cfg.get('authenticate_type', 2),
            'force': cfg.get('force', True),
            'cluster': cfg.get('cluster', 'ckcluster'),
            'logic_cluster': cfg.get('logic_cluster', 'cklogic'),
        }

    def _find_clickhouse_packages(self):
        pkg_dir = getattr(self.config, 'package_dir', '') or ''
        search_dir = os.path.join(pkg_dir, self.group) if self.group else pkg_dir
        self.logger.debug('[%s] 搜索 ClickHouse 安装包目录: %s', self.name, search_dir)
        if not os.path.isdir(search_dir):
            raise RuntimeError(
                '[{}] 未找到安装包目录: {}'.format(self.name, search_dir))
        pattern = os.path.join(search_dir, '*[Cc][Ll][Ii][Cc][Kk][Hh][Oo][Uu][Ss][Ee]*')
        packages = sorted(glob.glob(pattern))
        if not packages:
            raise RuntimeError(
                '[{}] 在 {} 中未找到 ClickHouse 安装包'.format(self.name, search_dir))
        return packages

    def _build_shards(self, hosts):
        total = len(hosts)
        if total < 2:
            raise RuntimeError('ClickHouse 至少需要 2 台主机')
        shard_count = total // 2
        shards = []
        idx = 0
        for _ in range(shard_count):
            replicas = []
            for _ in range(2):
                if idx < total:
                    replicas.append({'Ip': hosts[idx]})
                    idx += 1
            shards.append({'Replicas': replicas})
        return shards

    def _build_keeper_nodes(self, hosts):
        total = len(hosts)
        if total == 2:
            return [hosts[0]]
        return hosts[:3]

    def _prepare_ch_data_dirs(self, ch_hosts, ch_path):
        """在所有 ClickHouse 目标主机上提前创建数据目录"""
        servers_map = getattr(self.ctx, 'servers_map', {}) or {}
        for host in ch_hosts:
            server_info = servers_map.get(host)
            if not server_info:
                self.logger.warning('[%s] 未找到 SSH 配置，跳过创建数据目录', host)
                continue
            ssh = get_ssh_client(server_info, dry_run=self.ssh.dry_run, logger=self.logger)
            try:
                self.logger.info('[%s@%s] 创建 ClickHouse 数据目录: %s', self.name, host, ch_path)
                ssh.execute('mkdir -p {}'.format(shlex.quote(ch_path)))
            finally:
                ssh.close()

    def _copy_ssh_key_to_ckman(self, ckman_host):
        """将 ckman 主机上的 SSH 私钥复制到 ckman 安装目录的 conf/ 下"""
        servers_map = getattr(self.ctx, 'servers_map', {}) or {}
        server_info = servers_map.get(ckman_host)
        if not server_info:
            self.logger.warning('[ckman@%s] 未找到 SSH 配置，跳过复制 id_rsa', ckman_host)
            return

        ssh = get_ssh_client(server_info, dry_run=self.ssh.dry_run, logger=self.logger)
        try:
            ckman_conf_dir = '{}/ckman/conf'.format(self.comms_dir)
            ssh.execute('mkdir -p {}'.format(shlex.quote(ckman_conf_dir)))
            username = ssh.username or 'root'
            if username == 'root':
                ssh_key_path = '/root/.ssh/id_rsa'
            else:
                ssh_key_path = '/home/{}/.ssh/id_rsa'.format(username)

            code, _, _ = ssh.execute('test -f {}'.format(shlex.quote(ssh_key_path)))
            if code == 0:
                ssh.execute('cp {} {}'.format(
                    shlex.quote(ssh_key_path), shlex.quote(ckman_conf_dir)))
                self.logger.info('[ckman@%s] 已复制 %s 到 %s',
                                 ckman_host, ssh_key_path, ckman_conf_dir)
            else:
                self.logger.warning('[ckman@%s] %s 不存在，跳过复制',
                                    ckman_host, ssh_key_path)
        finally:
            ssh.close()

    def _extract_pkg_info(self, package_path):
        filename = os.path.basename(package_path)
        if '.' in filename:
            pkg_name = filename
            parts = filename.rsplit('.', 2)
            if len(parts) >= 3 and parts[-2] == 'x86_64':
                pkg_type = 'x86_64.rpm'
            else:
                pkg_type = parts[-1] if len(parts) > 1 else 'rpm'
        else:
            pkg_name = filename
            pkg_type = 'rpm'
        return pkg_name, pkg_type

    def _ckman_login_and_upload(self, ckman_host, ckman_port, packages):
        """登录 ckman 获取 token 并上传所有 ClickHouse 安装包"""
        self.logger.info('[ckman@%s] 登录 ckman 获取 token', ckman_host)
        token = ckman_login(ckman_host, ckman_port, 'ckman',
                            'Ckman123456!', self.logger)
        self.logger.info('[ckman@%s] 开始逐个上传 ClickHouse 安装包（共 %d 个）',
                         ckman_host, len(packages))
        for pkg in packages:
            result = ckman_upload_package(ckman_host, ckman_port, token, pkg, self.logger)
            self.logger.info('[ckman@%s] 上传 %s 结果: retCode=%s, retMsg=%s',
                             ckman_host, os.path.basename(pkg),
                             result.get('retCode'), result.get('retMsg'))
        return token

    def _prepare_clickhouse_hosts(self, ch_hosts, ch_cfg):
        """在 ClickHouse 目标主机上创建安装目录、数据目录，并复制 SSH 密钥到 ckman"""
        ch_install_dir = os.path.join(self.install_dir, 'clickhouse')
        self.logger.info('[%s] 创建 ClickHouse 安装目录: %s', self.name, ch_install_dir)
        self._prepare_ch_data_dirs(ch_hosts, ch_install_dir)
        self.logger.info('[%s] 确保 ClickHouse 数据目录存在: %s', self.name, ch_cfg['path'])
        self._prepare_ch_data_dirs(ch_hosts, ch_cfg['path'])

        ckman_host = self._get_ckman_host()
        self.logger.info('[ckman@%s] 复制 SSH 私钥到 ckman conf 目录', ckman_host)
        self._copy_ssh_key_to_ckman(ckman_host)

    def _build_deploy_body(self, ch_cfg, ch_hosts, pkg_name, pkg_type):
        """构建 ckman 部署 ClickHouse 集群的请求体"""
        shards = self._build_shards(ch_hosts)
        keeper_nodes = self._build_keeper_nodes(ch_hosts)
        return {
            'Cluster': ch_cfg['cluster'],
            'Comment': 'eoi ck',
            'PkgType': pkg_type,
            'PkgName': pkg_name,
            'LogicCluster': ch_cfg['logic_cluster'],
            'Shards': shards,
            'Protocol': 'native',
            'Port': ch_cfg['tcp_port'],
            'HttpPort': ch_cfg['http_port'],
            'Secure': False,
            'Keeper': 'clickhouse-keeper',
            'KeeperConf': {
                'Runtime': 'standalone',
                'KeeperNodes': keeper_nodes,
                'TcpPort': ch_cfg['keeper_tcp_port'],
                'RaftPort': ch_cfg['keeper_raft_port'],
                'Path': ch_cfg['path'],
                'Coordination': {
                    'OperationTimeoutMs': 10000,
                    'SessionTimeoutMs': 30000,
                    'ForceSync': False,
                    'AutoForwarding': False,
                },
            },
            'ZkPort': ch_cfg.get('zk_port',
                get_component_config(self.config, 'zookeeper').get('port', 2181)),
            'Password': ch_cfg['password'],
            'EncryptType': 0,
            'Path': ch_cfg['path'],
            'SshUser': ch_cfg['ssh_user'],
            'AuthenticateType': ch_cfg['authenticate_type'],
            'SshPort': ch_cfg['ssh_port'],
        }

    def install(self, skip_health_check=False):
        if self.config.debug:
            self.logger.info('[%s@%s] 调试模式：跳过 ClickHouse 部署（通过 ckman API）',
                             self.name, self.ssh.host)
            return

        self.logger.info('[%s@%s] === 开始通过 ckman 部署 ClickHouse ===',
                         self.name, self.ssh.host)

        ckman_host = self._get_ckman_host()
        ckman_cfg = get_component_config(self.config, 'ckman')
        ckman_port = ckman_cfg.get('port', 8808)
        ch_hosts = self._get_clickhouse_hosts()
        ch_cfg = self._get_clickhouse_config()
        packages = self._find_clickhouse_packages()

        token = self._ckman_login_and_upload(ckman_host, ckman_port, packages)
        self._prepare_clickhouse_hosts(ch_hosts, ch_cfg)

        pkg_name, pkg_type = self._extract_pkg_info(packages[0])
        deploy_body = self._build_deploy_body(ch_cfg, ch_hosts, pkg_name, pkg_type)
        self.logger.debug('[%s@%s] ClickHouse 部署请求体: %s',
                           self.name, self.ssh.host, deploy_body)
        force = 'true' if ch_cfg['force'] else 'false'

        self.logger.info('[ckman@%s] 部署 ClickHouse 集群: %s, shards=%d',
                         ckman_host, ch_cfg['cluster'],
                         len(deploy_body.get('Shards', [])))
        ckman_deploy_clickhouse(ckman_host, ckman_port, token,
                                deploy_body, self.logger)

        self.logger.info('[%s@%s] ClickHouse 部署任务已提交，'
                         '等待健康检查确认集群就绪',
                         self.name, self.ssh.host)

    def health_check(self):
        ClickHouseChecker(
            self.ssh, self.component_dir, self.config, self.logger,
            context=self.ctx
        ).check()
        self.logger.info('[%s@%s] ClickHouse 健康检查通过',
                         self.name, self.ssh.host)
