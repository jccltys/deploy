# -*- coding: utf-8 -*-
"""REFINER 组件安装器 — 双包部署（refiner-pro + refiner-pro-etl）"""
import os
import posixpath
import shlex

from installers.common.base_installer import BaseInstaller
from core.config_utils import (
    get_nacos_vars,
    get_mysql_vars,
    get_kafka_vars,
    get_zookeeper_vars,
    get_clickhouse_vars,
    get_redis_vars,
)
from tools.nacos_api import NacosConfigManager


class RefinerInstaller(BaseInstaller):
    GROUP = 'refiner'

    @property
    def component_dir(self):
        return self.apps_root

    def _refiner_vars(self):
        """从 config_utils 的独立 getter 函数组装 refiner 所需的所有变量"""
        nacos = get_nacos_vars(self.ctx, self.config) or {}
        mysql = get_mysql_vars(self.ctx, self.config) or {}
        kafka = get_kafka_vars(self.ctx, self.config) or {}
        zk = get_zookeeper_vars(self.ctx, self.config) or {}
        ck = get_clickhouse_vars(self.ctx, self.config) or {}
        redis = get_redis_vars(self.ctx, self.config) or {}

        # 组装 servers 列表
        nacos_host = '{}:{}'.format(
            nacos.get('nacos_hosts', ['127.0.0.1'])[0],
            nacos.get('nacos_port', 8848)
        )

        kafka_hosts = getattr(self.ctx, 'comp_hosts', {}).get('kafka', [])
        kafka_port = kafka.get('kafka_port', 9092)
        kafka_servers = ','.join(
            '{}:{}'.format(h, kafka_port) for h in kafka_hosts
        ) if kafka_hosts else ''

        zk_hosts = getattr(self.ctx, 'comp_hosts', {}).get('zookeeper', [])
        zk_port = zk.get('zookeeper_port', 2181)
        zk_servers = ','.join(
            '{}:{}'.format(h, zk_port) for h in zk_hosts
        ) if zk_hosts else ''

        ck_hosts = ck.get('clickhouse_hosts', [])
        ck_tcp_port = ck.get('clickhouse_tcp_port', 9000)
        ck_http_port = ck.get('clickhouse_http_port', 8123)
        ck_http_servers = ','.join(
            '{}:{}'.format(h, ck_http_port) for h in ck_hosts
        ) if ck_hosts else ''

        return {
            'nacos_host': nacos_host,
            'nacos_servers': nacos.get('nacos_servers', nacos_host),
            'nacos_user': nacos.get('nacos_user', 'nacos'),
            'nacos_password': nacos.get('nacos_password', '0192023A7BBD73250516F069DF18B500'),
            'mysql_host': mysql.get('mysql_host', '127.0.0.1'),
            'mysql_port': str(mysql.get('mysql_port', 3306)),
            'mysql_user': mysql.get('mysql_user', 'root'),
            'mysql_password': mysql.get('mysql_password', 'MySQL@123'),
            'kafka_host': kafka_hosts[0] if kafka_hosts else '127.0.0.1',
            'kafka_port': str(kafka_port),
            'kafka_servers': kafka_servers,
            'zookeeper_host': zk_hosts[0] if zk_hosts else '127.0.0.1',
            'zookeeper_port': str(zk_port),
            'zookeeper_servers': zk_servers,
            'clickhouse_host': ck_hosts[0] if ck_hosts else '127.0.0.1',
            'clickhouse_tcp_port': str(ck_tcp_port),
            'clickhouse_http_port': str(ck_http_port),
            'clickhouse_http_servers': ck_http_servers,
            'clickhouse_password': ck.get('clickhouse_password', 'ck@123'),
            'clickhouse_cluster': ck.get('clickhouse_cluster', 'ckcluster'),
            'redis_host': redis.get('redis_host', '127.0.0.1'),
            'redis_port': str(redis.get('redis_port', 6379)),
            'redis_password': redis.get('redis_password', 'Redis@123'),
            'redis_database': str(redis.get('redis_database', 0)),
            'sentinel_servers': redis.get('sentinel_servers', ''),
            'sentinel_name': redis.get('sentinel_name', 'mymaster'),
            'redis_hosts': sorted(getattr(self.ctx, 'comp_hosts', {}).get('redis', [])),
            'is_sentinel': len(sorted(getattr(self.ctx, 'comp_hosts', {}).get('redis', []))) == 3,
        }

    def _create_dirs(self):
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.apps_root)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.apps_root)))
        for subdir in ('customPlugins', 'plugins', 'plugins-config'):
            d = os.path.join(self.apps_root, subdir)
            self.ssh.execute('mkdir -p {}'.format(shlex.quote(d)))
            self.logger.info('[%s@%s] 创建子目录: %s', self.name, self.ssh.host, d)

    def _get_packages(self):
        pkg_dir = getattr(self.config, 'package_dir', '') or ''
        search_dir = os.path.join(pkg_dir, self.GROUP)
        archive_exts = ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.zip', '.tar', '.rpm')
        candidates = sorted(
            f for f in os.listdir(search_dir)
            if 'refiner' in f.lower()
            and f.lower().endswith(archive_exts)
        )
        etl = [f for f in candidates if 'etl' in f.lower()]
        pro = [f for f in candidates if 'etl' not in f.lower()]
        if not pro:
            pro = [f for f in candidates if 'refiner-pro' in f.lower()]
        if not etl:
            raise RuntimeError('[{}] 未找到 refiner-pro-etl 安装包'.format(self.name))
        if not pro:
            raise RuntimeError('[{}] 未找到 refiner-pro 安装包'.format(self.name))
        return pro[0], etl[0]

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

    def _patch_config_files(self):
        refiner_vars = self._refiner_vars()
        nacos_servers = refiner_vars.get('nacos_servers', '127.0.0.1:8848')
        nacos_password = refiner_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')
        nacos_user = refiner_vars.get('nacos_user', 'nacos')
        zookeeper_servers = refiner_vars.get('zookeeper_servers', '')

        def _yaml_replace(rel_path, replacements):
            full_path = os.path.join(self.apps_root, rel_path)
            code, content, _ = self.ssh.execute(
                'cat {} 2>/dev/null'.format(shlex.quote(full_path)))
            if code != 0:
                self.logger.warning('[%s@%s] 未找到 %s，跳过修改',
                                    self.name, self.ssh.host, rel_path)
                return
            changed = False
            for old, new in replacements:
                if old in content:
                    content = content.replace(old, new)
                    changed = True
            if changed:
                self.write_remote_file(full_path, content)
                self.logger.info('[%s@%s] 已更新: %s',
                                  self.name, self.ssh.host, rel_path)
            else:
                self.logger.info('[%s@%s] %s 无变化，跳过',
                                  self.name, self.ssh.host, rel_path)

        # bootstrap.yml 级别替换（Nacos config server 地址 + 命名空间 + 凭据）
        nacos_replaces = [
            ('server-addr: 127.0.0.1:8848', 'server-addr: {}'.format(nacos_servers)),
            ('server-addr: localhost:8848', 'server-addr: {}'.format(nacos_servers)),
            ('server-addr: 192.168.103.128:8848', 'server-addr: {}'.format(nacos_servers)),
            ('server-addr: 192.168.103.130:8848', 'server-addr: {}'.format(nacos_servers)),
            ('server-addr: 192.168.31.170:8848', 'server-addr: {}'.format(nacos_servers)),
            ('namespace: DEV-122', 'namespace: '),
            ('namespace: dev', 'namespace: '),
            ('namespace: wenbo', 'namespace: '),
            ('password: 0192023A7BBD73250516F069DF18B500', 'password: {}'.format(nacos_password)),
            ('password: nacos', 'password: {}'.format(nacos_password)),
            ('username: nacos', 'username: {}'.format(nacos_user)),
        ]

        for service in ('refiner-pro', 'refiner-pro-etl'):
            _yaml_replace(os.path.join(service, 'config', 'bootstrap.yml'), nacos_replaces)

        # bootstrap.yml 启用 Nacos 配置中心
        for service in ('refiner-pro', 'refiner-pro-etl'):
            _yaml_replace(os.path.join(service, 'config', 'bootstrap.yml'), [
                ('enabled: false', 'enabled: true'),
            ])

        # chameleon_zk.json 中的 ZooKeeper 地址（仅 refiner-pro 有此文件）
        if zookeeper_servers:
            _yaml_replace(os.path.join('refiner-pro', 'config', 'chameleon_zk.json'), [
                ('"server": "127.0.0.1:2181"', '"server": "{}"'.format(zookeeper_servers)),
            ])

    def _upload_nacos_configs(self):
        refiner_vars = self._refiner_vars()
        nacos_host = refiner_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_servers = refiner_vars.get('nacos_servers', nacos_host)
        nacos_user = refiner_vars.get('nacos_user', 'nacos')
        nacos_password = refiner_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')
        mysql_host = refiner_vars.get('mysql_host', '127.0.0.1')
        mysql_port = refiner_vars.get('mysql_port', '3306')
        mysql_password = refiner_vars.get('mysql_password', 'MySQL@123')
        kafka_servers = refiner_vars.get('kafka_servers', '')
        zookeeper_servers = refiner_vars.get('zookeeper_servers', '')
        clickhouse_http_servers = refiner_vars.get('clickhouse_http_servers', '')
        clickhouse_password = refiner_vars.get('clickhouse_password', 'ck@123')
        clickhouse_cluster = refiner_vars.get('clickhouse_cluster', 'ckcluster')
        redis_host = refiner_vars.get('redis_host', '127.0.0.1')
        redis_port = refiner_vars.get('redis_port', '6379')
        redis_password = refiner_vars.get('redis_password', 'Redis@123')
        redis_database = refiner_vars.get('redis_database', '0')
        sentinel_servers = refiner_vars.get('sentinel_servers', '')
        sentinel_name = refiner_vars.get('sentinel_name', 'mymaster')
        is_sentinel = refiner_vars.get('is_sentinel', False)

        apps_root = self.apps_root

        # 定位本地模板目录: conf/template/refiner/
        template_root = getattr(self.config, 'config_template_dir', '') or ''
        refiner_template_dir = os.path.join(template_root, 'refiner')
        if not os.path.isdir(refiner_template_dir):
            self.logger.warning('[%s@%s] 未找到 refiner 模板目录: %s',
                                self.name, self.ssh.host, refiner_template_dir)
            return

        # Nacos 登录
        mgr = NacosConfigManager(logger=self.logger)
        self.logger.info('[%s@%s] Nacos 登录认证', self.name, self.ssh.host)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        # 模板文件 → Nacos DataId 映射
        configs = [
            ('refiner.yaml', 'refiner'),
            ('refiner-etl.yaml', 'refiner-etl'),
        ]

        # 公共替换对（两个模板通用）
        nacos_addr_replaces = [
            ('server-addr: 192.168.31.170:8848', 'server-addr: {}'.format(nacos_servers)),
            ('username: nacos', 'username: {}'.format(nacos_user)),
        ]
        mysql_replaces = [
            ('url: jdbc:mysql://192.168.31.171:3306/refiner_pro',
             'url: jdbc:mysql://{}:{}/refiner_pro'.format(mysql_host, mysql_port)),
            ('    password: MySQL@123\n    # 由于部分逻辑涉及到更新是否成功',
             '    password: {}\n    # 由于部分逻辑涉及到更新是否成功'.format(mysql_password)),
        ]
        nacos_pwd_replace = (
            '        password: znyw@123\n        register-enabled:',
            '        password: {}\n        register-enabled:'.format(nacos_password),
        )

        for template_file, data_id in configs:
            template_path = os.path.join(refiner_template_dir, template_file)
            if not os.path.isfile(template_path):
                self.logger.warning('[%s@%s] 未找到本地模板 %s，跳过',
                                    self.name, self.ssh.host, template_path)
                continue

            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # --- refiner-pro 特有替换（clickhouse / redis / zk / plugin / sentinel）---
            is_pro = ('etl' not in template_file)

            if is_pro and is_sentinel:
                # 哨兵模式：先处理注释结构，再进行值替换
                for old, new in [
                    ('\n    host: ', '\n    #host: '),
                    ('\n    port: ', '\n    #port: '),
                    ('\n    #sentinel:', '\n    sentinel:'),
                    ('\n    #  master:', '\n      master:'),
                    ('\n    #  nodes:', '\n      nodes:'),
                ]:
                    if old in content:
                        content = content.replace(old, new)
                content = content.replace(
                    '      master: mymaster', '      master: {}'.format(sentinel_name))
                content = content.replace(
                    '      nodes: redis-host1:26379,redis-host2:26379,redis-host3:26379',
                    '      nodes: {}'.format(sentinel_servers))

            # --- 收集所有替换对并执行 ---
            replaces = []
            replaces.extend(nacos_addr_replaces)
            replaces.extend(mysql_replaces)
            replaces.append(nacos_pwd_replace)

            if is_pro:
                # refiner-pro 专属
                replaces.append((
                    'bootstrap-servers: 192.168.31.172:9092,192.168.31.173:9092,'
                    '192.168.31.174:9092',
                    'bootstrap-servers: {}'.format(kafka_servers),
                ))
                replaces.append((
                    '      password: znyw@123\n      url: jdbc:clickhouse',
                    '      password: {}\n      url: jdbc:clickhouse'.format(clickhouse_password),
                ))
                replaces.append((
                    'url: jdbc:clickhouse://192.168.31.170:8123,192.168.31.171:8123/refiner_pro',
                    'url: jdbc:clickhouse://{}/refiner_pro'.format(clickhouse_http_servers),
                ))
                replaces.append((
                    'clusterName: demo-clickhouse',
                    'clusterName: {}'.format(clickhouse_cluster),
                ))
                replaces.append((
                    '  redis:\n    host: 192.168.31.170\n    port: 6379',
                    '  redis:\n    host: {}\n    port: {}'.format(redis_host, redis_port),
                ))
                replaces.append((
                    '    password: Redis@123\n    database: 0',
                    '    password: {}\n    database: {}'.format(redis_password, redis_database),
                ))
                replaces.append((
                    'zookeeper: 192.168.31.172:2181,192.168.31.173:2181,'
                    '192.168.31.174:2181',
                    'zookeeper: {}'.format(zookeeper_servers),
                ))
                # Plugin path: /home/app/refiner-pro/ → {apps_root}/refiner-pro/
                replaces.append((
                    '/home/app/refiner-pro/',
                    os.path.join(apps_root, 'refiner-pro') + '/',
                ))
            else:
                # refiner-etl 专属
                replaces.append((
                    'bootstrap-servers: 192.168.31.172:9092,192.168.31.173:9092,'
                    '192.168.31.174:9092',
                    'bootstrap-servers: {}'.format(kafka_servers),
                ))

            for old, new in replaces:
                if old in content:
                    content = content.replace(old, new)

            self.logger.info('[%s@%s] 上传 %s 到 Nacos (dataId=%s)',
                             self.name, self.ssh.host, template_file, data_id)
            mgr.publish_config(nacos_host, data_id, content, token,
                               config_type='YAML', ssh=self.ssh)

    def prepare(self):
        self.logger.info('[%s@%s] === 开始准备 refiner（下载 + 解压 + 配置修改）===',
                          self.name, self.ssh.host)
        self._create_dirs()

        pro_pkg, etl_pkg = self._get_packages()

        pro_pkg_path = self._download_package(pro_pkg, self.apps_root)
        self._extract_package(pro_pkg_path, self.apps_root, 'refiner-pro')

        etl_pkg_path = self._download_package(etl_pkg, self.apps_root)
        self._extract_package(etl_pkg_path, self.apps_root, 'refiner-pro-etl')

        self.ssh.execute('rm -f {} {}'.format(
            shlex.quote(pro_pkg_path), shlex.quote(etl_pkg_path)))

        self._patch_config_files()
        self._upload_nacos_configs()
        self.logger.info('[%s@%s] === refiner 准备完成 ===', self.name, self.ssh.host)

    @classmethod
    def get_template_vars_doc(cls):
        base = super(RefinerInstaller, cls).get_template_vars_doc()
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
            'zookeeper_host': {
                'type': 'str', 'description': 'ZooKeeper 主机地址',
                'source': '从 deploy 映射推导', 'example': '192.168.1.6',
            },
            'zookeeper_port': {
                'type': 'str', 'description': 'ZooKeeper 端口',
                'source': 'config.yaml zookeeper.port', 'example': '2181',
            },
            'zookeeper_servers': {
                'type': 'str', 'description': 'ZooKeeper 服务地址列表 (逗号分隔)',
                'source': '从 deploy 映射推导', 'example': '192.168.1.6:2181,192.168.1.7:2181',
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
        })
        return base

    def template_vars(self, **overrides):
        refiner_vars = self._refiner_vars()
        self._with_common_app_vars(overrides, refiner_vars)
        overrides.setdefault('kafka_host', refiner_vars.get('kafka_host', '127.0.0.1'))
        overrides.setdefault('kafka_port', refiner_vars.get('kafka_port', '9092'))
        overrides.setdefault('kafka_servers', refiner_vars.get('kafka_servers', ''))
        overrides.setdefault('zookeeper_host', refiner_vars.get('zookeeper_host', '127.0.0.1'))
        overrides.setdefault('zookeeper_port', refiner_vars.get('zookeeper_port', '2181'))
        overrides.setdefault('zookeeper_servers', refiner_vars.get('zookeeper_servers', ''))
        overrides.setdefault('clickhouse_host', refiner_vars.get('clickhouse_host', '127.0.0.1'))
        overrides.setdefault('clickhouse_tcp_port', refiner_vars.get('clickhouse_tcp_port', '19000'))
        overrides.setdefault('clickhouse_http_port', refiner_vars.get('clickhouse_http_port', '18123'))
        overrides.setdefault('clickhouse_password', refiner_vars.get('clickhouse_password', 'ck@123'))
        return super().template_vars(**overrides)

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 REFINER 组件 ===', self.name, self.ssh.host)
        self.prepare()
        self._init_database()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self.logger.info('[%s@%s] === REFINER 组件安装完成 ===', self.name, self.ssh.host)

    def _init_database(self):
        refiner_vars = self._refiner_vars()
        self._init_app_database(refiner_vars, 'refiner_pro')

    def _start_service(self, service, port):
        start_script = os.path.join(self.apps_root, service, 'start.sh')
        code, _, _ = self.ssh.execute(
            'test -f {}'.format(shlex.quote(start_script)))
        if code != 0:
            self.logger.warning('[%s@%s] %s 未找到 start.sh，请手动启动',
                                self.name, self.ssh.host, service)
            return False
        unit_content = '''[Unit]
Description=Refiner {service_name}
After=network.target

[Service]
Type=forking
Environment=JAVA_HOME={java_home}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:{java_home}/bin
ExecStart={script}
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target'''.format(
            service_name=service,
            java_home=shlex.quote(self.java_home),
            script=shlex.quote(start_script))
        self._create_systemd_unit(service, unit_content)
        if self._use_systemd:
            self._enable_systemd_unit(service, start=True)
        else:
            self._script_start(
                'nohup bash -c "export JAVA_HOME={} && bash {}" > /dev/null 2>&1 &'.format(
                    shlex.quote(self.java_home), shlex.quote(start_script)))
        self.logger.info('[%s@%s] 等待 %s 启动（端口 %d）...',
                          self.name, self.ssh.host, service, port)
        if not self.wait_for_port(self.ssh.host, port, timeout=360, interval=10):
            raise RuntimeError(
                '[{}@{}] {} 启动超时，端口 {} 未就绪'
                .format(self.name, self.ssh.host, service, port))
        self.logger.info('[%s@%s] %s 启动成功', self.name, self.ssh.host, service)
        return True

    def start_service(self):
        self.logger.info('[%s@%s] 启动 REFINER 服务', self.name, self.ssh.host)
        refiner_cfg = getattr(self.config, 'refiner', {}) or {}
        pro_port = refiner_cfg.get('refiner_pro_port', 9091)
        etl_port = refiner_cfg.get('refiner_etl_port', 19091)

        # 先启动 refiner-pro，等待就绪后再启动 refiner-pro-etl
        self._start_service('refiner-pro', pro_port)
        self._start_service('refiner-pro-etl', etl_port)

    def health_check(self):
        refiner_cfg = getattr(self.config, 'refiner', {}) or {}
        pro_port = refiner_cfg.get('refiner_pro_port', 9091)
        etl_port = refiner_cfg.get('refiner_etl_port', 19091)

        self.logger.info('[%s@%s] 健康检查: refiner-pro 端口 %d, refiner-pro-etl 端口 %d',
                          self.name, self.ssh.host, pro_port, etl_port)

        for port, label in [(pro_port, 'refiner-pro'), (etl_port, 'refiner-pro-etl')]:
            if not self.wait_for_port(self.ssh.host, port, timeout=60, interval=5):
                raise RuntimeError(
                    '[{}@{}] REFINER 健康检查失败: {} 端口 {} 未就绪'
                    .format(self.name, self.ssh.host, label, port))

        # Nacos 服务注册检查
        refiner_vars = self._refiner_vars()
        nacos_host = refiner_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_user = refiner_vars.get('nacos_user', 'nacos')
        nacos_password = refiner_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')

        self.logger.info('[%s@%s] 检查 Nacos 服务注册状态', self.name, self.ssh.host)
        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('refiner', 'refiner-etl'):
            self.logger.info('[%s@%s] 等待 %s 注册到 Nacos...',
                              self.name, self.ssh.host, service_name)
            mgr.check_service_registration(
                nacos_host, service_name, token, ssh=self.ssh)
            self.logger.info('[%s@%s] %s Nacos 注册检查通过',
                              self.name, self.ssh.host, service_name)

        self.logger.info('[%s@%s] REFINER 健康检查通过（端口 + Nacos 注册）', self.name, self.ssh.host)
