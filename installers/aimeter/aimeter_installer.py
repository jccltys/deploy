# -*- coding: utf-8 -*-
"""AIMETER 组件安装器 — 三包部署（aimeter + scheduler + alert-copy-to-odmp）"""
import os
import posixpath
import shlex

from installers.common.base_installer import BaseInstaller
from core.config_utils import (
    get_aimeter_vars,
    get_nacos_vars,
    get_mysql_vars,
    get_kafka_vars,
    get_clickhouse_vars,
    get_redis_vars,
    get_component_config,
)
from core.mysql_db import init_database
from core.ssh_client import get_ssh_client
from tools.nacos_api import NacosConfigManager
from utils.update_spring_config import SpringConfigUpdater

try:
    from kafka.admin import KafkaAdminClient, NewTopic, ConfigResource
    from kafka.errors import TopicAlreadyExistsError
    _HAS_KAFKA_PYTHON = True
except ImportError:
    _HAS_KAFKA_PYTHON = False


class AimeterInstaller(BaseInstaller):
    GROUP = 'aimeter'

    @property
    def component_dir(self):
        return self.apps_root

    def _aimeter_vars(self):
        """从 config_utils 的独立 getter 函数组装 aimeter 所需的所有变量"""
        nacos = get_aimeter_vars(self.ctx, self.config) or {}
        nacos_all = get_nacos_vars(self.ctx, self.config) or {}
        mysql = get_mysql_vars(self.ctx, self.config) or {}
        kafka = get_kafka_vars(self.ctx, self.config) or {}
        ck = get_clickhouse_vars(self.ctx, self.config) or {}
        redis = get_redis_vars(self.ctx, self.config) or {}

        nacos_host = '{}:{}'.format(
            nacos.get('nacos_hosts', ['127.0.0.1'])[0],
            nacos.get('nacos_port', 8848)
        ) if 'nacos_hosts' in nacos else nacos.get('nacos_host', '127.0.0.1:8848')
        nacos_servers = nacos_all.get('nacos_servers', nacos_host)

        kafka_hosts = getattr(self.ctx, 'comp_hosts', {}).get('kafka', [])
        kafka_port = kafka.get('kafka_port', 9092)
        kafka_servers = ','.join(
            '{}:{}'.format(h, kafka_port) for h in kafka_hosts
        ) if kafka_hosts else ''

        ck_hosts = ck.get('clickhouse_hosts', [])
        ck_tcp_port = ck.get('clickhouse_tcp_port', 9000)
        ck_http_port = ck.get('clickhouse_http_port', 8123)

        return {
            'nacos_host': nacos.get('nacos_host', '127.0.0.1:8848'),
            'nacos_servers': nacos_servers,
            'nacos_user': nacos.get('nacos_user', 'nacos'),
            'nacos_password': nacos.get('nacos_password', '0192023A7BBD73250516F069DF18B500'),
            'mysql_host': mysql.get('mysql_host', '127.0.0.1'),
            'mysql_port': str(mysql.get('mysql_port', 3306)),
            'mysql_user': mysql.get('mysql_user', 'root'),
            'mysql_password': mysql.get('mysql_password', 'MySQL@123'),
            'kafka_host': kafka_hosts[0] if kafka_hosts else '127.0.0.1',
            'kafka_port': str(kafka_port),
            'kafka_servers': kafka_servers,
            'clickhouse_host': ck_hosts[0] if ck_hosts else '127.0.0.1',
            'clickhouse_tcp_port': str(ck_tcp_port),
            'clickhouse_http_port': str(ck_http_port),
            'clickhouse_http_servers': ck.get('clickhouse_host_http_ports', ''),
            'clickhouse_password': ck.get('clickhouse_password', 'ck@123'),
            'clickhouse_cluster': ck.get('clickhouse_cluster', 'hsbk'),
            'clickhouse_logic': ck.get('clickhouse_logic_cluster', 'cklogic'),
            'redis_host': redis.get('redis_host', '127.0.0.1'),
            'redis_port': str(redis.get('redis_port', 6379)),
            'redis_password': redis.get('redis_password', 'Redis@123'),
            'redis_database': str(redis.get('redis_database', 0)),
            'sentinel_servers': redis.get('sentinel_servers', ''),
            'sentinel_name': redis.get('sentinel_name', 'mymaster'),
        }

    def _get_packages(self):
        """在包目录中查找 3 个 aimeter 安装包"""
        pkg_dir = getattr(self.config, 'package_dir', '') or ''
        search_dir = os.path.join(pkg_dir, self.GROUP)
        archive_exts = ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.zip', '.tar', '.rpm')
        candidates = sorted(
            f for f in os.listdir(search_dir)
            if 'aimeter' in f.lower()
            and f.lower().endswith(archive_exts)
        )
        main_pkg = [f for f in candidates if 'scheduler' not in f.lower() and 'alert' not in f.lower()]
        scheduler_pkg = [f for f in candidates if 'scheduler' in f.lower()]
        alert_pkg = [f for f in candidates if 'alert' in f.lower() and 'scheduler' not in f.lower()]

        if not main_pkg:
            raise RuntimeError('[{}] 未找到 aimeter 主安装包（不含 scheduler/alert 关键字）'.format(self.name))
        if not scheduler_pkg:
            raise RuntimeError('[{}] 未找到 aimeter-scheduler 安装包'.format(self.name))
        if not alert_pkg:
            raise RuntimeError('[{}] 未找到 aimeter-alert 安装包'.format(self.name))

        return main_pkg[0], scheduler_pkg[0], alert_pkg[0]

    def _create_dirs(self):
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.apps_root)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.apps_root)))

    def _download_package(self, package_file, target_dir):
        target = os.path.join(target_dir, package_file)
        pkg_url = 'http://{}:{}/{}/{}'.format(
            self.config.host_ip, self.config.http_port, self.GROUP, package_file)
        self.logger.info('[%s@%s] 下载安装包: %s', self.name, self.ssh.host, package_file)
        self.logger.info('[%s@%s] 下载地址: %s', self.name, self.ssh.host, pkg_url)
        cmd = 'curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
            shlex.quote(target), pkg_url)
        code, out, err = self.ssh.execute(cmd)
        if code != 0:
            raise RuntimeError('[{}@{}] 下载 {} 失败: {}'.format(
                self.name, self.ssh.host, package_file, err.strip()[:200]))
        return target

    def _extract_package(self, pkg_path, target_dir, symlink_name):
        pkg_file = os.path.basename(pkg_path)
        self.logger.info('[%s@%s] 解压安装包: %s', self.name, self.ssh.host, pkg_file)

        extract_cmd_tpl, expected_basename = self._archive_ext(pkg_file)

        if self.ssh.dry_run:
            extracted_path = posixpath.join(target_dir, expected_basename)
            self.logger.info('[%s@%s] (调试模式) 模拟解压到: %s',
                              self.name, self.ssh.host, extracted_path)
            pkg_version = self._extract_version_from_package(pkg_file)
            versioned = '{}-{}'.format(expected_basename, pkg_version) if pkg_version else expected_basename
            self.ssh.execute('ln -snf {} {}'.format(
                shlex.quote(versioned),
                shlex.quote(posixpath.join(target_dir, symlink_name))))
            return symlink_name, versioned, extracted_path

        root_q = shlex.quote(target_dir)
        code, before, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(root_q))
        before_set = set(before.strip().split('\n')) if before.strip() else set()

        pkg_q = shlex.quote(pkg_path)
        cmd = extract_cmd_tpl.format(pkg=pkg_q, dir=root_q)
        code, out, err = self.ssh.execute(cmd)
        if code != 0:
            if self.package_file.endswith('.zip'):
                raise RuntimeError('[{}@{}] 解压失败: {}'.format(self.name, self.ssh.host, err))
            cmd = 'tar -xzf {} -C {}'.format(pkg_q, root_q)
            code, out, err = self.ssh.execute(cmd)
        if code != 0:
            cmd = 'tar -xJf {} -C {}'.format(pkg_q, root_q)
            code, out, err = self.ssh.execute(cmd)
        if code != 0:
            raise RuntimeError('[{}@{}] 解压 {} 失败: {}'.format(
                self.name, self.ssh.host, pkg_file, err))

        code, after, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(root_q))
        after_set = set(after.strip().split('\n')) if after.strip() else set()
        new_entries = after_set - before_set
        new_dirs = [e for e in new_entries if e]
        if not new_dirs:
            raise RuntimeError('[{}@{}] 解压 {} 后未发现新目录'.format(
                self.name, self.ssh.host, pkg_file))

        extracted_basename = sorted(new_dirs)[0].rstrip('/')
        extracted_path = posixpath.join(target_dir, extracted_basename)

        pkg_version = self._extract_version_from_package(pkg_file)
        if pkg_version and not extracted_basename.endswith(pkg_version):
            versioned_name = '{}-{}'.format(extracted_basename, pkg_version)
            self.logger.info('[%s@%s] 重命名解压目录: %s -> %s',
                              self.name, self.ssh.host,
                              extracted_basename, versioned_name)
            self.ssh.execute('mv {} {}'.format(
                shlex.quote(extracted_path),
                shlex.quote(posixpath.join(target_dir, versioned_name))))
            extracted_basename = versioned_name
            extracted_path = posixpath.join(target_dir, versioned_name)

        symlink_path = posixpath.join(target_dir, symlink_name)
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(extracted_basename), shlex.quote(symlink_path)))
        self.logger.info('[%s@%s] 软链接: %s -> %s',
                          self.name, self.ssh.host,
                          symlink_path, extracted_basename)

        return symlink_name, extracted_basename, extracted_path

    def _get_base_replace_map(self):
        """构建基础替换映射（供 _patch_config_files 和 _upload_nacos_configs 共用）

        只包含部署时必须覆盖的变量（IP、端口、密码），其余使用模板默认值。
        """
        aimeter_vars = self._aimeter_vars()
        mysql_host = aimeter_vars.get('mysql_host', '127.0.0.1')
        mysql_port = aimeter_vars.get('mysql_port', '3306')
        mysql_password = aimeter_vars.get('mysql_password', 'MySQL@123')
        mysql_user = aimeter_vars.get('mysql_user', 'root')
        kafka_servers = aimeter_vars.get('kafka_servers', '')
        ck_http_servers = aimeter_vars.get('clickhouse_http_servers', '')
        ck_password = aimeter_vars.get('clickhouse_password', 'ck@123')
        ck_cluster = aimeter_vars.get('clickhouse_cluster', 'hsbk')
        ck_logic = aimeter_vars.get('clickhouse_logic', 'cklogic')
        redis_host = aimeter_vars.get('redis_host', '127.0.0.1')
        redis_port = aimeter_vars.get('redis_port', '6379')
        redis_password = aimeter_vars.get('redis_password', 'Redis@123')
        nacos_host = aimeter_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_servers = aimeter_vars.get('nacos_servers', nacos_host)
        nacos_password = aimeter_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')
        nacos_user = aimeter_vars.get('nacos_user', 'nacos')

        # 与 RedisInstaller._is_sentinel_mode() 保持一致
        redis_hosts = getattr(self.ctx, 'comp_hosts', {}).get('redis', [])
        is_sentinel = len(redis_hosts) == 3

        return {
            'NACOS_HOST': nacos_servers,
            'NACOS_USER': nacos_user,
            'NACOS_PASSWORD': nacos_password,
            'NACOS_NAMESPACE': '',
            'MYSQL_HOST': '{}:{}'.format(mysql_host, mysql_port),
            'MYSQL_USER': mysql_user,
            'MYSQL_PASSWORD': mysql_password,
            'MYSQL_DB': 'aimeter',
            'CLICKHOUSE_HOST': ck_http_servers,
            'CLICKHOUSE_USER': 'default',
            'CLICKHOUSE_PASSWORD': ck_password,
            'CLICKHOUSE_DB': 'aimeter',
            'CLICKHOUSE_CLUSTER': ck_cluster,
            'CLICKHOUSE_LOGIC': ck_logic,
            'REDIS_HOST': redis_host,
            'REDIS_PORT': redis_port,
            'REDIS_PASSWORD': redis_password,
            'REDIS_MODE': 'sentinel' if is_sentinel else 'single',
            'REDIS_SENTINEL_MASTER': aimeter_vars.get('sentinel_name', 'mymaster'),
            'REDIS_SENTINEL_NODES': aimeter_vars.get('sentinel_servers',
                '192.168.31.173:26379,192.168.31.170:26379,192.168.31.171:26379'),
            'KAFKA_HOST': kafka_servers,
            'XXL_PORT': '36890',
            'FLYWAY_SQL_ENABLED': 'true',
            'FLYWAY_CK_ENABLED': 'true',
        }

    def _patch_config_files(self):
        base_replace_map = self._get_base_replace_map()

        # 与 RedisInstaller._is_sentinel_mode() 保持一致
        redis_hosts = getattr(self.ctx, 'comp_hosts', {}).get('redis', [])
        is_sentinel = len(redis_hosts) == 3
        self.logger.info('[%s] Redis 主机数: %d, 模式: %s',
                          self.name, len(redis_hosts),
                          'sentinel' if is_sentinel else 'single')

        def _patch_spring(rel_path, extra_map=None):
            """对远程 properties 文件执行 Spring ${VAR:default} 替换"""
            full_path = os.path.join(self.apps_root, rel_path)
            code, content, _ = self.ssh.execute(
                'cat {} 2>/dev/null'.format(shlex.quote(full_path)))
            if code != 0:
                self.logger.warning('[%s@%s] 未找到 %s，跳过修改',
                                    self.name, self.ssh.host, rel_path)
                return
            replace_map = dict(base_replace_map)
            if extra_map:
                replace_map.update(extra_map)
            patched = SpringConfigUpdater.batch_replace(content, replace_map, inline=False)
            if is_sentinel:
                patched = patched.replace(
                    '\n#spring.redis.sentinel.master=', '\nspring.redis.sentinel.master=')
                patched = patched.replace(
                    '\n#spring.redis.sentinel.nodes=', '\nspring.redis.sentinel.nodes=')
            else:
                patched = patched.replace(
                    '\nspring.redis.sentinel.master=', '\n#spring.redis.sentinel.master=')
                patched = patched.replace(
                    '\nspring.redis.sentinel.nodes=', '\n#spring.redis.sentinel.nodes=')
            if patched != content:
                self.write_remote_file(full_path, patched)
                self.logger.info('[%s@%s] 已更新: %s',
                                  self.name, self.ssh.host, rel_path)
            else:
                self.logger.info('[%s@%s] %s 无变化，跳过',
                                  self.name, self.ssh.host, rel_path)

        # -- aimeter 服务 --
        for filename in ('bootstrap.properties', 'application-common.properties'):
            _patch_spring(os.path.join('aimeter', 'config', filename))
        _patch_spring(os.path.join('aimeter', 'config', 'application-prd.properties'),
                      extra_map={'SERVER_PORT': '36888'})

        # -- aimeter-scheduler 服务 --
        for filename in ('bootstrap.properties', 'application-common.properties'):
            _patch_spring(os.path.join('aimeter-scheduler', 'config', filename))
        _patch_spring(os.path.join('aimeter-scheduler', 'config', 'application-prd.properties'),
                      extra_map={'SERVER_PORT': '36889'})

    def _upload_nacos_configs(self):
        aimeter_vars = self._aimeter_vars()
        nacos_host = aimeter_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_user = aimeter_vars.get('nacos_user', 'nacos')
        nacos_password = aimeter_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')

        mgr = NacosConfigManager(logger=self.logger)
        self.logger.info('[%s@%s] Nacos 登录认证', self.name, self.ssh.host)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        template_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'conf', 'template', 'aimeter')
        base_replace_map = self._get_base_replace_map()

        templates = [
            ('aimeter-common.properties', None),
            ('aimeter.properties', {'SERVER_PORT': '36888'}),
            ('aimeter-scheduler.properties', {'SERVER_PORT': '36889'}),
        ]

        for filename, extra_map in templates:
            local_path = os.path.join(template_dir, filename)
            if not os.path.exists(local_path):
                self.logger.warning(
                    '[%s@%s] 未找到本地模板: %s，跳过 Nacos 上传',
                    self.name, self.ssh.host, local_path)
                continue

            with open(local_path, 'r') as f:
                content = f.read()

            replace_map = dict(base_replace_map)
            if extra_map:
                replace_map.update(extra_map)
            rendered = SpringConfigUpdater.batch_replace(content, replace_map, inline=False)

            # 与 _patch_config_files 一致，切换 Redis 哨兵配置注释
            is_sentinel = replace_map.get('REDIS_MODE', 'single') == 'sentinel'
            if is_sentinel:
                rendered = rendered.replace(
                    '\n#spring.redis.sentinel.master=', '\nspring.redis.sentinel.master=')
                rendered = rendered.replace(
                    '\n#spring.redis.sentinel.nodes=', '\nspring.redis.sentinel.nodes=')
            else:
                rendered = rendered.replace(
                    '\nspring.redis.sentinel.master=', '\n#spring.redis.sentinel.master=')
                rendered = rendered.replace(
                    '\nspring.redis.sentinel.nodes=', '\n#spring.redis.sentinel.nodes=')

            data_id = filename
            self.logger.info('[%s@%s] 上传 %s 到 Nacos (dataId=%s)',
                              self.name, self.ssh.host, filename, data_id)
            mgr.publish_config(nacos_host, data_id, rendered, token,
                               config_type='Properties', ssh=self.ssh)

    def _copy_alert_to_odmp(self, alert_pkg):
        """将 aimeter-alert 安装包拷贝到 ODMP 主机"""
        odmp_hosts = getattr(self.ctx, 'comp_hosts', {}).get('odmp', [])
        if not odmp_hosts:
            self.logger.warning('[%s@%s] 未找到 ODMP 主机，跳过 alert 拷贝',
                                self.name, self.ssh.host)
            return

        odmp_host = odmp_hosts[0]
        servers_map = getattr(self.ctx, 'servers_map', {}) or {}
        server_info = servers_map.get(odmp_host)
        if not server_info:
            self.logger.warning('[%s@%s] 未找到 ODMP 主机 %s 的 SSH 配置，跳过 alert 拷贝',
                                self.name, self.ssh.host, odmp_host)
            return

        self.logger.info('[%s@%s] 拷贝 %s 到 ODMP 主机 %s',
                          self.name, self.ssh.host, alert_pkg, odmp_host)

        odmp_ssh = get_ssh_client(server_info, dry_run=self.ssh.dry_run, logger=self.logger)
        try:
            target_dir = os.path.join(self.config.apps_dir, 'aimeter')
            odmp_ssh.execute('mkdir -p {}'.format(shlex.quote(target_dir)))

            alert_url = 'http://{}:{}/{}/{}'.format(
                self.config.host_ip, self.config.http_port,
                self.GROUP, alert_pkg)
            target_path = os.path.join(target_dir, alert_pkg)
            odmp_ssh.execute('curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
                shlex.quote(target_path), alert_url))
            self.logger.info('[%s@%s] %s 已拷贝到 %s:%s',
                              self.name, self.ssh.host, alert_pkg, odmp_host, target_path)
        finally:
            odmp_ssh.close()

    def _fix_restart_sh_line_endings(self, service):
        """将 restart.sh 的行尾符转换为 unix 格式"""
        restart_script = os.path.join(self.apps_root, service, 'restart.sh')
        code, _, _ = self.ssh.execute(
            'test -f {}'.format(shlex.quote(restart_script)))
        if code != 0:
            self.logger.warning('[%s@%s] %s 未找到 restart.sh，跳过行尾转换',
                                self.name, self.ssh.host, service)
            return False
        self.logger.info('[%s@%s] 转换 %s/restart.sh 行尾符为 unix',
                          self.name, self.ssh.host, service)
        self.ssh.execute(
            "sed -i 's/\\r$//' {}".format(shlex.quote(restart_script)))
        return True

    def prepare(self):
        self.logger.info('[%s@%s] === 开始准备 aimeter（下载 + 解压 + 配置修改）===',
                          self.name, self.ssh.host)
        self._create_dirs()

        main_pkg, scheduler_pkg, alert_pkg = self._get_packages()

        # 下载并解压主包和 scheduler
        main_pkg_path = self._download_package(main_pkg, self.apps_root)
        self._extract_package(main_pkg_path, self.apps_root, 'aimeter')

        sch_pkg_path = self._download_package(scheduler_pkg, self.apps_root)
        _, _, sch_extracted = self._extract_package(sch_pkg_path, self.apps_root, 'aimeter-scheduler')
        self.ssh.execute('chmod 755 {}'.format(shlex.quote(sch_extracted)))

        # 清理已解压的包文件
        self.ssh.execute('rm -f {} {}'.format(
            shlex.quote(main_pkg_path), shlex.quote(sch_pkg_path)))

        # alert 包拷贝到 ODMP 主机（下载到 aimeter 主机再清理）
        alert_pkg_path = self._download_package(alert_pkg, self.apps_root)
        self._copy_alert_to_odmp(alert_pkg)
        self.ssh.execute('rm -f {}'.format(shlex.quote(alert_pkg_path)))

        self._patch_config_files()
        self._upload_nacos_configs()
        self.logger.info('[%s@%s] === aimeter 准备完成 ===', self.name, self.ssh.host)

    @classmethod
    def get_template_vars_doc(cls):
        base = super(AimeterInstaller, cls).get_template_vars_doc()
        base.update(cls._app_common_template_vars_doc())
        base.update({
            'kafka_host': {
                'type': 'str', 'description': 'Kafka 主机地址',
                'source': '从 deploy 映射推导', 'example': '192.168.1.4',
            },
            'kafka_port': {
                'type': 'str', 'description': 'Kafka 端口',
                'source': 'config.yaml kafka.port', 'example': '9092',
            },
            'kafka_servers': {
                'type': 'str', 'description': 'Kafka 服务地址列表 (逗号分隔)',
                'source': '从 deploy 映射推导', 'example': '192.168.1.4:9092,192.168.1.5:9092',
            },
            'clickhouse_host': {
                'type': 'str', 'description': 'ClickHouse 主机地址',
                'source': '从 deploy 映射推导', 'example': '192.168.1.8',
            },
            'clickhouse_tcp_port': {
                'type': 'str', 'description': 'ClickHouse TCP 端口',
                'source': 'config.yaml clickhouse.tcp_port', 'example': '19000',
            },
            'clickhouse_http_port': {
                'type': 'str', 'description': 'ClickHouse HTTP 端口',
                'source': 'config.yaml clickhouse.http_port', 'example': '18123',
            },
            'clickhouse_password': {
                'type': 'str', 'description': 'ClickHouse 密码',
                'source': 'config.yaml clickhouse.password', 'example': 'ck@123',
            },
            'redis_host': {
                'type': 'str', 'description': 'Redis 主机地址',
                'source': '从 deploy 映射推导', 'example': '192.168.1.9',
            },
            'redis_port': {
                'type': 'str', 'description': 'Redis 端口',
                'source': 'config.yaml redis.port', 'example': '6379',
            },
            'redis_password': {
                'type': 'str', 'description': 'Redis 密码',
                'source': 'config.yaml redis.password', 'example': 'Redis@123',
            },
            'redis_database': {
                'type': 'str', 'description': 'Redis 数据库编号',
                'source': 'config.yaml redis.database', 'example': '0',
            },
        })
        return base

    def template_vars(self, **overrides):
        aimeter_vars = self._aimeter_vars()
        self._with_common_app_vars(overrides, aimeter_vars)
        overrides.setdefault('kafka_host', aimeter_vars.get('kafka_host', '127.0.0.1'))
        overrides.setdefault('kafka_port', aimeter_vars.get('kafka_port', '9092'))
        overrides.setdefault('kafka_servers', aimeter_vars.get('kafka_servers', ''))
        overrides.setdefault('clickhouse_host', aimeter_vars.get('clickhouse_host', '127.0.0.1'))
        overrides.setdefault('clickhouse_tcp_port', aimeter_vars.get('clickhouse_tcp_port', '19000'))
        overrides.setdefault('clickhouse_http_port', aimeter_vars.get('clickhouse_http_port', '18123'))
        overrides.setdefault('clickhouse_password', aimeter_vars.get('clickhouse_password', 'ck@123'))
        overrides.setdefault('redis_host', aimeter_vars.get('redis_host', '127.0.0.1'))
        overrides.setdefault('redis_port', aimeter_vars.get('redis_port', '6379'))
        overrides.setdefault('redis_password', aimeter_vars.get('redis_password', 'Redis@123'))
        overrides.setdefault('redis_database', aimeter_vars.get('redis_database', '0'))
        return super().template_vars(**overrides)

    def _create_kafka_topics(self):
        """通过 kafka-python AdminClient 创建 aimeter 需要的 topic"""
        if not _HAS_KAFKA_PYTHON:
            self.logger.warning('[%s@%s] kafka-python 未安装，跳过 topic 创建',
                                self.name, self.ssh.host)
            return

        kafka_hosts = getattr(self.ctx, 'comp_hosts', {}).get('kafka', [])
        if not kafka_hosts:
            self.logger.warning('[%s@%s] 未找到 Kafka 主机，跳过 topic 创建',
                                self.name, self.ssh.host)
            return

        bootstrap_servers = ['{}:{}'.format(h, 9092) for h in kafka_hosts]
        topic_name = 'aimeter_discovery'
        num_partitions = 6
        rf = min(3, len(kafka_hosts))

        if self.ssh.dry_run:
            self.logger.info('[%s@%s] 调试模式: 跳过 topic 创建（分区=%d, 副本=%d）',
                              self.name, self.ssh.host, num_partitions, rf)
            return

        try:
            admin = KafkaAdminClient(
                bootstrap_servers=bootstrap_servers,
                client_id='aimeter-installer',
                request_timeout_ms=10000,
            )

            metadata = admin.list_topics()
            if topic_name in metadata.topics():
                self.logger.info('[%s@%s] Kafka topic %s 已存在，跳过创建',
                                  self.name, self.ssh.host, topic_name)
            else:
                topic = NewTopic(
                    name=topic_name,
                    num_partitions=num_partitions,
                    replication_factor=rf,
                )
                admin.create_topics([topic])
                self.logger.info('[%s@%s] Kafka topic %s 创建成功（%d 分区, %d 副本）',
                                  self.name, self.ssh.host, topic_name,
                                  num_partitions, rf)

            admin.close()
        except Exception as e:
            self.logger.warning('[%s@%s] Kafka topic 操作失败: %s',
                                self.name, self.ssh.host, e)

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 AIMETER 组件 ===', self.name, self.ssh.host)
        self.prepare()
        self._create_kafka_topics()
        self._init_database()
        self.start_service()
        if not skip_health_check:
            self.health_check()
            self._run_upgrade_sql()
        self.logger.info('[%s@%s] === AIMETER 组件安装完成 ===', self.name, self.ssh.host)

    def _init_database(self):
        """上传 SQL 文件到远程主机，创建数据库（不执行 SQL，留到健康检查后）"""
        aimeter_vars = self._aimeter_vars()
        mysql_host = aimeter_vars.get('mysql_host', '127.0.0.1')
        mysql_port = aimeter_vars.get('mysql_port', '3306')
        mysql_user = aimeter_vars.get('mysql_user', 'root')
        mysql_password = aimeter_vars.get('mysql_password', 'MySQL@123')

        local_sql = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'lib', 'aimeter', 'aimeter_upgrade.sql')
        remote_sql = os.path.join(self.apps_root, 'aimeter_upgrade.sql')

        if os.path.exists(local_sql):
            with open(local_sql, 'r') as f:
                sql_content = f.read()
            self.write_remote_file(remote_sql, sql_content)
            self.logger.info('[%s@%s] SQL 文件已上传到: %s',
                              self.name, self.ssh.host, remote_sql)
            self._remote_sql = remote_sql
        else:
            self.logger.warning('[%s@%s] 未找到本地 SQL 文件: %s，跳过 SQL 执行',
                                self.name, self.ssh.host, local_sql)
            self._remote_sql = None

        self._init_app_database(aimeter_vars, 'aimeter')

    def _run_upgrade_sql(self):
        """健康检查通过后，在 aimeter 数据库上执行升级 SQL"""
        if not getattr(self, '_remote_sql', None):
            self.logger.info('[%s@%s] 无 SQL 文件可执行，跳过',
                              self.name, self.ssh.host)
            return
        aimeter_vars = self._aimeter_vars()
        mysql_host = aimeter_vars.get('mysql_host', '127.0.0.1')
        mysql_port = aimeter_vars.get('mysql_port', '3306')
        mysql_user = aimeter_vars.get('mysql_user', 'root')
        mysql_password = aimeter_vars.get('mysql_password', 'MySQL@123')

        self.logger.info('[%s@%s] 执行升级 SQL: %s',
                          self.name, self.ssh.host, self._remote_sql)
        init_database(
            self.ssh, self.install_dir,
            mysql_host, mysql_port, mysql_user, mysql_password,
            'aimeter', sql_file=self._remote_sql, logger=self.logger)
        self.logger.info('[%s@%s] 升级 SQL 执行完成',
                          self.name, self.ssh.host)

    def _start_service(self, service, port):
        self._fix_restart_sh_line_endings(service)

        restart_script = os.path.join(self.apps_root, service, 'restart.sh')
        code, _, _ = self.ssh.execute(
            'test -f {}'.format(shlex.quote(restart_script)))
        if code != 0:
            self.logger.warning('[%s@%s] %s 未找到 restart.sh，请手动启动',
                                self.name, self.ssh.host, service)
            return False

        unit_content = '''[Unit]
Description=AIMETER {service_name}
After=network.target

[Service]
Type=forking
Environment=JAVA_HOME={java_home}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:{java_home}/bin
WorkingDirectory={apps_root}/{service_name}
ExecStart={script}
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target'''.format(
            service_name=service,
            java_home=shlex.quote(self.java_home),
            apps_root=shlex.quote(self.apps_root),
            script=shlex.quote(restart_script))
        self._create_systemd_unit(service, unit_content)
        if self._use_systemd:
            self._enable_systemd_unit(service, start=True)
        else:
            script_dir = os.path.dirname(restart_script)
            self._script_start(
                'cd {} && export JAVA_HOME={} && bash {} &'.format(
                    shlex.quote(script_dir),
                    shlex.quote(self.java_home),
                    shlex.quote(restart_script)))

        self.logger.info('[%s@%s] 等待 %s 启动（端口 %d）...',
                          self.name, self.ssh.host, service, port)
        if not self.wait_for_port(self.ssh.host, port, timeout=360, interval=10):
            raise RuntimeError(
                '[{}@{}] {} 启动超时，端口 {} 未就绪'
                .format(self.name, self.ssh.host, service, port))
        self.logger.info('[%s@%s] %s 启动成功', self.name, self.ssh.host, service)
        return True

    def start_service(self):
        self.logger.info('[%s@%s] 启动 AIMETER 服务', self.name, self.ssh.host)
        aimeter_cfg = getattr(self.config, 'aimeter', {}) or {}
        alert_port = aimeter_cfg.get('alert_port', 36888)
        sch_port = aimeter_cfg.get('alert_sch_port', 36889)

        # 先启动 aimeter（alert），再启动 scheduler
        self._start_service('aimeter', alert_port)
        self._start_service('aimeter-scheduler', sch_port)

    def health_check(self):
        aimeter_cfg = getattr(self.config, 'aimeter', {}) or {}
        alert_port = aimeter_cfg.get('alert_port', 36888)
        sch_port = aimeter_cfg.get('alert_sch_port', 36889)

        self.logger.info('[%s@%s] 健康检查: aimeter 端口 %d, aimeter-scheduler 端口 %d',
                          self.name, self.ssh.host, alert_port, sch_port)

        for port, label in [(alert_port, 'aimeter'), (sch_port, 'aimeter-scheduler')]:
            if not self.wait_for_port(self.ssh.host, port, timeout=60, interval=5):
                raise RuntimeError(
                    '[{}@{}] AIMETER 健康检查失败: {} 端口 {} 未就绪'
                    .format(self.name, self.ssh.host, label, port))

        # Nacos 服务注册检查
        aimeter_vars = self._aimeter_vars()
        nacos_host = aimeter_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_user = aimeter_vars.get('nacos_user', 'nacos')
        nacos_password = aimeter_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')

        self.logger.info('[%s@%s] 检查 Nacos 服务注册状态', self.name, self.ssh.host)
        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('aimeter', 'aimeter-scheduler'):
            self.logger.info('[%s@%s] 等待 %s 注册到 Nacos...',
                              self.name, self.ssh.host, service_name)
            mgr.check_service_registration(
                nacos_host, service_name, token, ssh=self.ssh)
            self.logger.info('[%s@%s] %s Nacos 注册检查通过',
                              self.name, self.ssh.host, service_name)

        self.logger.info('[%s@%s] AIMETER 健康检查通过（端口 + Nacos 注册）',
                          self.name, self.ssh.host)
