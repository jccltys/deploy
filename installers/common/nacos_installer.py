# -*- coding: utf-8 -*-
import base64
import json
import os
import re
import shlex
import threading
import time
from string import Template

from installers.common.base_installer import BaseInstaller
from utils.health import NacosChecker as _NacosChecker
from core.mysql_db import init_database
from core.health_check import run_health_checks
from core.ssh_client import get_ssh_client
from core.config_utils import (
    get_nacos_vars, get_mysql_vars, get_kafka_vars,
    get_redis_vars, get_clickhouse_vars, get_zookeeper_vars,
    get_component_config,
)
from tools.nacos_api import NacosConfigManager


class NacosInstaller(BaseInstaller):
    GROUP = 'common'
    DEPLOY_MODE = 'cluster'

    @classmethod
    def get_template_vars_doc(cls):
        base = super(NacosInstaller, cls).get_template_vars_doc()
        base.update({
            'nacos_servers': {
                'type': 'str',
                'description': 'Nacos 集群节点配置（每行一个 IP）',
                'source': '自动从 deploy 映射推导（节点数=3时生成）',
                'example': '192.168.1.2:8848\n192.168.1.3:8848\n192.168.1.4:8848',
            },
        })
        return base

    def _get_nacos_hosts(self):
        """获取 nacos 主机列表"""
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('nacos', []))

    def _is_cluster(self):
        """判断是否为集群模式（节点数 = 3）"""
        return len(self._get_nacos_hosts()) == 3

    def template_vars(self, **overrides):
        hosts = self._get_nacos_hosts()
        nacos_vars = get_nacos_vars(self.ctx, self.config) or {}
        nacos_port = nacos_vars.get('nacos_port', 8848)
        mysql_vars = get_mysql_vars(self.ctx, self.config) or {}
        mysql_port = mysql_vars.get('mysql_port', 3306)

        # MySQL 连接信息（取第一个 MySQL 主机，如未部署则 fallback 到本机）
        mysql_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('mysql', []))
        overrides.setdefault('mysql_host', mysql_hosts[0] if mysql_hosts else self.ssh.host)
        overrides.setdefault('mysql_port', str(mysql_port))
        overrides.setdefault('mysql_user', 'root')
        overrides.setdefault('nacos_port', str(nacos_port))

        if self._is_cluster():
            cluster_hosts = hosts[:3]
            servers = []
            for host in cluster_hosts:
                servers.append('{}:{}'.format(host, nacos_port))
            overrides.setdefault('nacos_servers', '\n'.join(servers))
        else:
            overrides.setdefault('nacos_servers', '{}:{}'.format(self.ssh.host, nacos_port))
        return super().template_vars(**overrides)

    def _is_valid_host(self):
        hosts = self._get_nacos_hosts()
        if not hosts:
            return False

        if self._is_cluster():
            cluster_hosts = hosts[:3]
            if self.ssh.host not in cluster_hosts:
                return False
        else:
            if self.ssh.host != hosts[0]:
                return False

        return True

    def extract_package(self):
        super().extract_package()
        versioned_name = re.sub(
            r'\.(tar\.(gz|xz|bz2)|tgz|zip)$', '', self.package_file, flags=re.I
        )
        symlink = self.component_dir
        old_path = self._extracted_path
        new_path = os.path.join(self.comms_dir, versioned_name)
        self.logger.info('[%s@%s] 重命名 %s -> %s',
                         self.name, self.ssh.host, self._extracted_basename, versioned_name)
        self.ssh.execute('mv {} {}'.format(shlex.quote(old_path), shlex.quote(new_path)))
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(versioned_name), shlex.quote(symlink)))
        self._extracted_basename = versioned_name
        self._extracted_path = new_path

    def prepare(self):
        """准备阶段：创建目录、下载安装包、解压、创建软链接、渲染配置、清理安装包（不包含 DB 初始化和启动）"""
        if not self._is_valid_host():
            return

        self.logger.info('[%s@%s] === 开始准备（下载 + 解压 + 配置文件）===', self.name, self.ssh.host)
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._create_data_dirs()
        self._rendered_files = []
        self.render_configs()
        self._save_config_snapshot()
        self._cleanup_package()
        self.logger.info('[%s@%s] === 准备完成 ===', self.name, self.ssh.host)

    def render_configs(self):
        """覆盖基类：仅渲染 conf/ 下的顶层文件（即 application.properties），跳过子目录

        基类 render_configs 使用 os.walk 递归遍历整个模板目录，这会把 Nacos 配置项
        （DEFAULT_GROUP/*.yaml、alert/app.conf 等）也复制到安装目录中，但这些文件只应
        通过 _upload_nacos_configs() 上传到 Nacos 服务端，不应出现在本地文件系统上。
        """
        template_root = getattr(self.config, 'config_template_dir', '') or ''
        if not template_root or not os.path.isdir(template_root):
            self.logger.warning('[%s@%s] 未找到配置模板根目录: %s',
                                self.name, self.ssh.host, template_root)
            return
        comp_template_dir = os.path.join(template_root, self.name)
        if not os.path.isdir(comp_template_dir):
            self.logger.warning('[%s@%s] 未找到配置模板: %s',
                                self.name, self.ssh.host, comp_template_dir)
            return

        self.logger.info('[%s@%s] 渲染配置模板目录: %s', self.name, self.ssh.host, comp_template_dir)

        # Nacos 服务端配置文件在 conf/ 下（如 conf/application.properties），
        # 而非模板根目录下。DEFAULT_GROUP/、alert/ 等子目录是 Nacos 配置项，只应通过
        # _upload_nacos_configs 上传，不应出现在本地安装目录中。
        conf_src = os.path.join(comp_template_dir, 'conf')
        if not os.path.isdir(conf_src):
            self.logger.warning('[%s@%s] 未找到 conf/ 子目录: %s', self.name, self.ssh.host, conf_src)
            return

        vars = self.template_vars()
        file_count = 0
        for fn in sorted(os.listdir(conf_src)):
            if fn.startswith('.') or fn == 'Thumbs.db':
                continue
            local_path = os.path.join(conf_src, fn)
            if os.path.isdir(local_path):
                # 跳过子目录（DEFAULT_GROUP/、alert/ 等是通过 _upload_nacos_configs 上传的 Nacos 配置项）
                continue
            file_count += 1
            # 远程路径保持 conf/ 前缀（如 conf/application.properties）
            rel_path = os.path.join('conf', fn)
            remote_path = os.path.join(self.component_dir, rel_path)
            self.ssh.execute('mkdir -p $(dirname {})'.format(shlex.quote(remote_path)))

            with open(local_path, 'r') as fh:
                content = fh.read()
            unresolved = re.findall(r'\$\{(.*?)\}', content)
            if unresolved:
                missing = [v for v in unresolved if v not in vars]
                if missing:
                    self.logger.warning('[%s@%s] 模板 %s 有未提供的变量: %s',
                                        self.name, self.ssh.host, local_path, missing)

            rendered = Template(content).safe_substitute(**vars)
            unresolved_after = re.findall(r'\$\{(.*?)\}', rendered)
            if unresolved_after:
                self.logger.warning('[%s@%s] 模板 %s 存在未替换的变量: %s',
                                    self.name, self.ssh.host, local_path, unresolved_after)
            self.logger.info('[%s@%s] 正在生成配置文件: %s', self.name, self.ssh.host, remote_path)
            encoded = base64.b64encode(rendered.encode()).decode()
            remote_q = shlex.quote(remote_path)
            cmd = "echo '{}' | base64 -d > {}".format(encoded, remote_q)
            self.ssh.execute(cmd, check=True, log_command=False)
            self.ssh.execute('chmod 644 {}'.format(remote_q))
            self._rendered_files.append((rel_path, rendered))
        self.logger.info('[%s@%s] 配置文件渲染完成，共 %d 个文件',
                         self.name, self.ssh.host, file_count)

    def _init_database(self):
        """数据库初始化（建库+建表），委托给 core.mysql_db 模块"""
        hosts = self._get_nacos_hosts()
        if self.ssh.host != hosts[0]:
            return

        self.logger.info('[%s@%s] 由第一个 Nacos 节点执行数据库初始化', self.name, self.ssh.host)

        vars = self.template_vars()
        mysql_host = vars.get('mysql_host', self.ssh.host)
        mysql_port = vars.get('mysql_port', '3306')
        db_user = vars.get('mysql_user', 'root')
        db_pwd = getattr(self.config, 'mysql_password', 'MySQL@123')
        db_name = 'nacos'
        sql_init = os.path.join(self.component_dir, 'conf', 'mysql-schema.sql')

        init_database(self.ssh, self.install_dir, mysql_host, mysql_port,
                      db_user, db_pwd, db_name, sql_init, self.logger)

    def install(self, skip_health_check=False):
        """覆盖基类 install，先把数据库初始化插到启动之前"""
        if not self._is_valid_host():
            return

        self.logger.info('[%s@%s] === 开始安装 ===', self.name, self.ssh.host)
        self.prepare()

        self._init_database()

        self.start_service()
        if not skip_health_check:
            self.health_check()
            self._upload_nacos_configs()
        self.logger.info('[%s@%s] === 安装完成 ===', self.name, self.ssh.host)

    def _create_data_dirs(self):
        super()._create_data_dirs()
        if self._is_cluster():
            hosts = self._get_nacos_hosts()[:3]
            nacos_vars = get_nacos_vars(self.ctx, self.config) or {}
            nacos_port = nacos_vars.get('nacos_port', 8848)
            content = '\n'.join('{}:{}'.format(h, nacos_port) for h in hosts) + '\n'
            cluster_file = os.path.join(self.component_dir, 'conf', 'cluster.conf')
            self.logger.info('[%s@%s] 集群模式，创建 cluster.conf: %s',
                            self.name, self.ssh.host, content.strip().replace('\n', ', '))
            self.write_remote_file(cluster_file, content)

    def start_service(self):
        mode = '集群' if self._is_cluster() else '单节点'
        self.logger.info('[%s@%s] 启动 Nacos（%s模式）', self.name, self.ssh.host, mode)
        cd = shlex.quote(self.component_dir)
        jh = shlex.quote(self.java_home)
        mode_flag = '' if self._is_cluster() else '-m standalone'
        unit = '''[Unit]
Description=Nacos
After=network.target

[Service]
Type=forking
Environment=JAVA_HOME={jh}
ExecStart={cd}/bin/startup.sh {mode}
ExecStop={cd}/bin/shutdown.sh
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(jh=jh, cd=cd, mode=mode_flag)
        self._create_systemd_unit('nacos', unit)
        if self._use_systemd:
            self._enable_systemd_unit('nacos', start=True)
        else:
            self._script_start('export JAVA_HOME={} && {}/bin/startup.sh {}'.format(jh, cd, mode_flag))

    def _deploy_vars(self):
        """聚合部署变量，供上传 Nacos 配置时替换硬编码地址"""
        nacos = get_nacos_vars(self.ctx, self.config) or {}
        mysql = get_mysql_vars(self.ctx, self.config) or {}
        kafka = get_kafka_vars(self.ctx, self.config) or {}
        redis = get_redis_vars(self.ctx, self.config) or {}
        ck = get_clickhouse_vars(self.ctx, self.config) or {}
        zk = get_zookeeper_vars(self.ctx, self.config) or {}

        nacos_host = '{}:{}'.format(
            (nacos.get('nacos_hosts') or ['127.0.0.1'])[0],
            nacos.get('nacos_port', 8848))
        nacos_servers = nacos.get('nacos_servers', nacos_host)
        mysql_host = mysql.get('mysql_host', '127.0.0.1')
        mysql_port = str(mysql.get('mysql_port', 3306))
        mysql_user = mysql.get('mysql_user', 'root')
        mysql_password = mysql.get('mysql_password', 'MySQL@123')
        kafka_servers = kafka.get('kafka_servers', '')
        redis_host = redis.get('redis_host', '127.0.0.1')
        redis_port = str(redis.get('redis_port', 6379))
        redis_password = redis.get('redis_password', 'Redis@123')
        sentinel_servers = redis.get('sentinel_servers', '')
        sentinel_name = redis.get('sentinel_name', 'mymaster')
        redis_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('redis', []))
        is_sentinel = len(redis_hosts) == 3
        ck_http = ck.get('clickhouse_host_http_ports', '')
        ck_tcp = ck.get('clickhouse_host_tcp_ports', '')
        ck_password = ck.get('clickhouse_password', 'ck@123')
        ck_cluster = ck.get('clickhouse_cluster', 'ckcluster')
        zk_servers = zk.get('zookeeper_servers', '')
        zk_host = zk.get('zookeeper_host', '127.0.0.1')
        zk_port = str(zk.get('zookeeper_port', 2181))

        nginx_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('nginx', []))
        nginx_cfg = get_component_config(self.config, 'nginx')
        nginx_host = nginx_hosts[0] if nginx_hosts else '127.0.0.1'
        nginx_port = str(nginx_cfg.get('listen_port', 10082))

        sso_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('sso', []))
        sso_host = sso_hosts[0] if sso_hosts else '127.0.0.1'

        odc_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('odc', []))
        odc_host = odc_hosts[0] if odc_hosts else '127.0.0.1'

        ck_hosts_list = [h.split(':')[0] for h in ck_tcp.split(',')] if ck_tcp else []

        return {
            'nacos_host': nacos_host,
            'nacos_servers': nacos_servers,
            'nacos_user': nacos.get('nacos_user', 'nacos'),
            'nacos_password': nacos.get('nacos_password', '0192023A7BBD73250516F069DF18B500'),
            'mysql_host': mysql_host,
            'mysql_port': mysql_port,
            'mysql_user': mysql_user,
            'mysql_password': mysql_password,
            'kafka_servers': kafka_servers,
            'redis_host': redis_host,
            'redis_port': redis_port,
            'redis_password': redis_password,
            'sentinel_servers': sentinel_servers,
            'sentinel_name': sentinel_name,
            'is_sentinel': is_sentinel,
            'ck_http_servers': ck_http,
            'ck_tcp_servers': ck_tcp,
            'ck_password': ck_password,
            'ck_cluster': ck_cluster,
            'zk_servers': zk_servers or '{}:{}'.format(zk_host, zk_port),
            'zk_host': zk_host,
            'zk_port': zk_port,
            'nginx_host': nginx_host,
            'nginx_port': nginx_port,
            'sso_host': sso_host,
            'odc_host': odc_host,
            'ck_hosts_list': ck_hosts_list,
        }

    def _build_nacos_replacements(self, vars):
        """基于部署变量构建地址替换映射（规范地址 → 实际部署地址）

        模板文件使用 192.168.31.x 规范地址，在此替换为实际部署值。
        各域替换分组为独立列表，最终合并返回。
        """
        mysql_addr = '{}:{}'.format(vars['mysql_host'], vars['mysql_port'])
        redis_addr = '{}:{}'.format(vars['redis_host'], vars['redis_port'])
        zk_addr = vars['zk_servers']

        pairs = []

        # -- MySQL 地址 --
        pairs.extend([
            ('jdbc:mysql://192.168.31.171:3306/', 'jdbc:mysql://{}/'.format(mysql_addr)),
            ('UQ_MYSQL_SERVER:192.168.31.171:3306', 'UQ_MYSQL_SERVER:{}'.format(mysql_addr)),
            ('192.168.31.171:3306/odc', '{}/odc'.format(mysql_addr)),
            ('192.168.31.171:3306/xxl_job', '{}/xxl_job'.format(mysql_addr)),
        ])

        # -- MySQL 密码（优先匹配带上下文的完整模式，避免误伤）--
        pairs.extend([
            ('\n    password: MySQL@123', '\n    password: {}'.format(vars['mysql_password'])),
            ('\n      # 密码（需要修改）\n      password: MySQL@123',
             '\n      # 密码（需要修改）\n      password: {}'.format(vars['mysql_password'])),
            ('\n        # 密码 （需要修改）\n        password: MySQL@123',
             '\n        # 密码 （需要修改）\n        password: {}'.format(vars['mysql_password'])),
            ('spring.datasource.password=MySQL@123',
             'spring.datasource.password={}'.format(vars['mysql_password'])),
            ('\n    password: 123456', '\n    password: {}'.format(vars['mysql_password'])),
            ('#password: 123456', '#password: {}'.format(vars['mysql_password'])),
        ])

        # -- Kafka --
        kafka = vars['kafka_servers']
        if kafka:
            pairs.extend([
                ('192.168.31.172:9092,192.168.31.173:9092,192.168.31.174:9092', kafka),
                ('"192.168.31.172:9092"', '"{}"'.format(kafka)),
            ])

        # -- Redis 单机模式 --
        _pwd = vars['redis_password']
        _host = vars['redis_host']
        _port = vars['redis_port']
        pairs.extend([
            ('    address: redis://192.168.31.170:6379\n    # 密码（需要修改）\n    password: Reids@123',
             '    address: redis://{}:{}\n    # 密码（需要修改）\n    password: {}'.format(_host, _port, _pwd)),
            ('    address: redis://192.168.31.170:6379\n    # 密码（需要修改）\n    password: eoi@123',
             '    address: redis://{}:{}\n    # 密码（需要修改）\n    password: {}'.format(_host, _port, _pwd)),
            ('\n    host: 192.168.31.170\n    port: 6379\n    password: Reids@123',
             '\n    host: {}\n    port: {}\n    password: {}'.format(_host, _port, _pwd)),
            ('redis://192.168.31.170:6379', 'redis://{}'.format(redis_addr)),
            ('nodes = "192.168.31.170:6379"', 'nodes = "{}:{}"'.format(_host, _port)),
            ('\n    mode: single\n    host: 192.168.31.170\n    port: 6379\n    database: 0\n    password: Reids@123',
             '\n    mode: single\n    host: {}\n    port: {}\n    database: 0\n    password: {}'.format(_host, _port, _pwd)),
            ('\n      host: 192.168.31.170\n      port: 6379\n      password: Reids@123',
             '\n      host: {}\n      port: {}\n      password: {}'.format(_host, _port, _pwd)),
            ('\n    host: 192.168.31.170\n    port: 6379\n    password: eoi@123',
             '\n    host: {}\n    port: {}\n    password: {}'.format(_host, _port, _pwd)),
        ])

        # Redis HOCON 密码（znyw@123 上下文，避免误伤同文件中的 Nacos 密码）
        pairs.extend([
            ('"redis",\n    password = "znyw@123"',
             '"redis",\n    password = "{}"'.format(_pwd)),
            # nacos 块中的密码（以 username = "nacos" 为上下文标记）
            ('  username = "nacos"\n  password = "znyw@123"',
             '  username = "nacos"\n  password = "{}"'.format(vars['nacos_password'])),
            # 兜底：其余位置的 "znyw@123"（通常是 redis 块中的密码）
            ('password = "znyw@123"', 'password = "{}"'.format(_pwd)),
        ])

        # -- Redis 哨兵模式 --
        sentinel_servers = vars.get('sentinel_servers', '')
        sentinel_name = vars.get('sentinel_name', 'mymaster')
        if vars.get('is_sentinel', False):
            pairs.extend([
                ('nodes = "192.168.31.173:26379,192.168.31.170:26379,192.168.31.171:26379"',
                 'nodes = "{}"'.format(sentinel_servers)),
                ('nodes: redis-host1:26379,redis-host2:26379,redis-host3:26379',
                 'nodes: {}'.format(sentinel_servers)),
                ('sentinelAddress: redis://192.168.107.204:26379, redis://192.168.107.204:26389',
                 'sentinelAddress: redis://{}'.format(sentinel_servers.replace(',', ',redis://'))),
                ('nodeAddress: redis://192.168.107.204:6379, redis://192.168.107.204:6389, redis://192.168.107.205:6379, redis://192.168.107.205:6389, redis://192.168.107.206:6379, redis://192.168.107.206:6389',
                 'nodeAddress: redis://{}'.format(','.join('redis://{}'.format(s) for s in sentinel_servers.split(',')))),
                ('\n    #  master: mymaster', '\n    #  master: {}'.format(sentinel_name)),
                ('\n    #  nodes: redis-host1:26379,redis-host2:26379,redis-host3:26379',
                 '\n    #  nodes: {}'.format(sentinel_servers)),
            ])
        pairs.extend([
            ('masterName = "mymaster"', 'masterName = "{}"'.format(sentinel_name)),
            ('#masterName = "mymaster"', '#masterName = "{}"'.format(sentinel_name)),
        ])

        # -- ZooKeeper --
        if zk_addr:
            pairs.extend([
                ('zookeeper: 192.168.31.175:2181', 'zookeeper: {}'.format(zk_addr)),
                ('host = "192.168.31.175:2181"', 'host = "{}"'.format(zk_addr)),
                ('192.168.31.172:2181,192.168.31.173:2181,192.168.31.174:2181', zk_addr),
            ])

        # -- ClickHouse --
        ck_http = vars['ck_http_servers']
        ck_tcp = vars['ck_tcp_servers']
        ck_pwd = vars['ck_password']
        if ck_http:
            pairs.append(('jdbc:clickhouse://192.168.31.170:8123,192.168.31.171:8123',
                           'jdbc:clickhouse://{}'.format(ck_http)))
        if ck_tcp:
            ck_tcp_port = ck_tcp.split(',')[0].split(':')[1] if ':' in ck_tcp.split(',')[0] else '19000'
            pairs.extend([
                ('"port": 9000,', '"port": {},'.format(ck_tcp_port)),
                ('"hosts": [["192.168.31.170","192.168.31.171"]],\n        "port": 9000',
                 '"hosts": [{}],\n        "port": {}'.format(
                     json.dumps([h.split(':')[0] for h in ck_tcp.split(',')]), ck_tcp_port)),
            ])
        pairs.append(('password: Hsbk@123', 'password: {}'.format(ck_pwd)))

        # -- Nacos 地址（所有节点，方便客户端 failover）--
        nacos_servers = vars['nacos_servers']
        pairs.extend([
            ('serverAddr = "192.168.31.170:8848"', 'serverAddr = "{}"'.format(nacos_servers)),
            ('serverAddr = "192.168.31.170:28848"', 'serverAddr = "{}"'.format(nacos_servers)),
        ])

        # -- ODC YAML 专用替换（nginx 地址 + dao-path）--
        nginx_addr = '{}:{}'.format(vars['nginx_host'], vars['nginx_port'])
        odc_dao_path = '{}/apps/odc/app_backend/odc/dao'.format(self.install_dir)
        pairs.extend([
            ('nginx: http://192.168.31.170:10082', 'nginx: http://{}'.format(nginx_addr)),
            ('dao-path: /apps/odc/app_backend/odc/dao', 'dao-path: {}'.format(odc_dao_path)),
            ('dao-path: /eoi/odc/dao', 'dao-path: {}'.format(odc_dao_path)),
        ])

        # -- origin YAML 专用替换（Redis + SSO + nginx URLs）--
        sso_host = vars['sso_host']
        nginx_host = vars['nginx_host']
        nginx_port = vars['nginx_port']
        pairs.extend([
            # origin-prod redis（spring.data.redis 下 6 空格缩进）
            ('\n      host: 192.168.31.170\n      port: 6379\n      password: Reids@123',
             '\n      host: {}\n      port: {}\n      password: {}'.format(_host, _port, _pwd)),
            # origin-test redis（spring.redis 下 4 空格缩进）
            ('\n    host: 192.168.31.170\n    port: 6379\n    password: Reids@123',
             '\n    host: {}\n    port: {}\n    password: {}'.format(_host, _port, _pwd)),
            # SSO baseUrl
            ('baseUrl: http://192.168.31.170:8080', 'baseUrl: http://{}:8080'.format(sso_host)),
            ('refererUrl: http://192.168.31.170:8080/authentication/portal',
             'refererUrl: http://{}:8080/authentication/portal'.format(sso_host)),
            # nginx URLs
            ('"http://192.168.31.170:10082/', '"http://{}:{}/'.format(nginx_host, nginx_port)),
            ('"http://192.168.31.170/externalLogin', '"http://{}/externalLogin'.format(nginx_host)),
            ('"http://192.168.31.170:10082/externalLogin',
             '"http://{}:{}/externalLogin'.format(nginx_host, nginx_port)),
            ('domain: http://192.168.31.170:9876', 'domain: http://{}:9876'.format(nginx_host)),
        ])

        # -- CK JSON 替换（sinkerAlert / sinkerCK / transSinker 共用）--
        ck_host_list = vars.get('ck_hosts_list', [])
        if len(ck_host_list) >= 2:
            pairs.extend([
                ('"cluster": "hsbk"', '"cluster": "{}"'.format(vars['ck_cluster'])),
                ('"password": "Hsbk@123"', '"password": "{}"'.format(ck_pwd)),
            ])
            shards = []
            for i in range(0, len(ck_host_list), 2):
                s_pair = ck_host_list[i:i+2]
                if len(s_pair) == 2:
                    shards.append(s_pair)
            if shards:
                pairs.extend([
                    ('["192.168.31.170", "192.168.31.171"]',
                     ', '.join('[{}]'.format(', '.join('"{}"'.format(h) for h in s))
                               for s in shards)),
                    ('[\n                "192.168.31.170",\n                "192.168.31.171"\n            ]',
                     ',\n            '.join(
                         '[\n                "{}",\n                "{}"\n            ]'.format(s[0], s[1])
                         for s in shards)),
                ])

        # -- alert/app.conf 中 Nacos HOCON 密码 + Redis HOCON 密码 --
        pairs.extend([
            ('password = "nacos"', 'password = "{}"'.format(vars['nacos_password'])),
            ('password = "Reids@123"', 'password = "{}"'.format(_pwd)),
        ])

        return pairs

    def _upload_nacos_configs(self):
        """Nacos 健康检查通过后，上传配置到 Nacos public 空间

        仅由第一个 Nacos 节点执行。遍历 conf/template/nacos/conf/ 下各子目录中的文件：
        - 子目录名 = Nacos Group
        - 文件名 = DataId
        - 文件内容中的硬编码地址会被替换为实际部署值
        """
        hosts = self._get_nacos_hosts()
        if self.ssh.host != hosts[0]:
            return

        vars = self._deploy_vars()
        nacos_host = vars['nacos_host']
        nacos_user = vars['nacos_user']
        nacos_password = vars['nacos_password']

        # 定位本地模板目录: deploy/conf/template/nacos/conf/
        template_root = getattr(self.config, 'config_template_dir', '') or ''
        nacos_conf_dir = os.path.join(template_root, self.name, 'conf')
        if not os.path.isdir(nacos_conf_dir):
            self.logger.info('[%s@%s] 未找到 Nacos 上传配置目录: %s，跳过',
                              self.name, self.ssh.host, nacos_conf_dir)
            return

        replaces = self._build_nacos_replacements(vars)

        self.logger.info('[%s@%s] 扫描 Nacos 上传配置: %s',
                          self.name, self.ssh.host, nacos_conf_dir)

        # 收集所有上传文件
        upload_files = []  # (group, data_id, local_path)
        for entry in sorted(os.listdir(nacos_conf_dir)):
            entry_path = os.path.join(nacos_conf_dir, entry)
            if not os.path.isdir(entry_path) or entry.startswith('.'):
                continue
            group = entry
            for fn in sorted(os.listdir(entry_path)):
                if fn.startswith('.') or fn == 'Thumbs.db':
                    continue
                upload_files.append((group, fn, os.path.join(entry_path, fn)))

        if not upload_files:
            self.logger.info('[%s@%s] Nacos 上传配置目录为空，跳过',
                              self.name, self.ssh.host)
            return

        # 读取并替换配置内容
        configs = []  # (group, data_id, content, config_type)
        for group, data_id, local_path in upload_files:
            with open(local_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 依次替换硬编码地址
            for old, new in replaces:
                if old in content:
                    content = content.replace(old, new)

            # 根据 redis 模式切换配置注释
            is_sentinel = vars.get('is_sentinel', False)
            sv = vars.get('sentinel_servers', '')  # 哨兵节点地址列表，仅数据用途
            if data_id in ('odc-prod.yaml', 'odc-test.yaml'):
                if is_sentinel:
                    # ODC 哨兵模式：注释掉单机 host/port，取消注释 sentinel/master/nodes
                    for o, n in [
                        ('\n    host: ', '\n    #host: '),
                        ('\n    port: ', '\n    #port: '),
                        ('\n    #sentinel:', '\n    sentinel:'),
                        ('\n    #  master:', '\n      master:'),
                        ('\n    #  nodes:', '\n      nodes:'),
                    ]:
                        if o in content:
                            content = content.replace(o, n)

            if data_id in ('origin-prod.yaml', 'origin-test.yaml'):
                if is_sentinel:
                    # origin 哨兵模式：结构为 spring.(data.)redis，
                    # host/port 为 4~6 空格缩进，sentinel 注释带空格（# sentinel: 而非 #sentinel:）
                    host_pat = '\n      host: ' if 'origin-prod' in data_id else '\n    host: '
                    port_pat = '\n      port: ' if 'origin-prod' in data_id else '\n    port: '
                    content = content.replace(host_pat, '\n      #host: ' if 'origin-prod' in data_id else '\n    #host: ')
                    content = content.replace(port_pat, '\n      #port: ' if 'origin-prod' in data_id else '\n    #port: ')
                    for o, n in [
                        ('\n    # sentinel:', '\n    sentinel:'),
                        ('\n    #   master:', '\n      master:'),
                        ('\n    #   nodes:', '\n      nodes:'),
                    ]:
                        if o in content:
                            content = content.replace(o, n)
                    for o, n in [
                        ('\n    enabled: true', '\n    #enabled: true'),
                        ('\n    address: redis://', '\n    #address: redis://'),
                    ]:
                        if o in content:
                            content = content.replace(o, n)
                    content = content.replace('\n    password: ', '\n    #password: ')
                    for o, n in [
                        ('\n    # mode: sentinel', '\n    mode: sentinel'),
                        ('\n    # masterName: mymaster',
                         '\n    masterName: {}'.format(vars.get('sentinel_name', 'mymaster'))),
                        ('\n    # enabled: true', '\n    enabled: true'),
                        ('\n    # password: redis@123',
                         '\n    password: {}'.format(vars['redis_password'])),
                    ]:
                        if o in content:
                            content = content.replace(o, n)
                    content = re.sub(
                        r'\n( +)# sentinelAddress: .*',
                        r'\n\1sentinelAddress: redis://{}'.format(
                            sv.replace(',', ',redis://')),
                        content,
                    )
                else:
                    # 单机模式：模板单机段已默认正确（enabled: true 未注释，address/password 由 _build_nacos_replacements 的 pairs 替换）
                    pass

            # HOCON app.conf Redis 哨兵模式切换
            if data_id == 'app.conf' and group in ('alert', 'processor', 'standardMetric'):
                # alert 用 2 空格缩进，processor/standardMetric 用 4 空格缩进
                indent = '  ' if group == 'alert' else '    '
                if is_sentinel:
                    content = content.replace('\n' + indent + '#mode = "sentinel"',
                                              '\n' + indent + 'mode = "sentinel"')
                    # masterName 已被 _build_nacos_replacements 的全局 pair 替换为实际名，搜索已替换后的值
                    master_name = vars.get('sentinel_name', 'mymaster')
                    content = content.replace('\n' + indent + '#masterName = "{}"'.format(master_name),
                                              '\n' + indent + 'masterName = "{}"'.format(master_name))
                    content = content.replace('\n' + indent + 'mode = "single"',
                                              '\n' + indent + '#mode = "single"')
                    # nodes 已由 _build_nacos_replacements 替换为 redis_host:redis_port，
                    # 哨兵模式下再替换为哨兵节点地址
                    redis_addr = '{}:{}'.format(vars['redis_host'], vars['redis_port'])
                    content = content.replace('nodes = "{}"'.format(redis_addr),
                                              'nodes = "{}"'.format(sv))
                # 单机模式：模板默认正确，无需额外处理

            # 根据扩展名推断 config_type
            ext = os.path.splitext(data_id)[1].lower()
            type_map = {'.yaml': 'YAML', '.yml': 'YAML', '.json': 'JSON',
                        '.properties': 'Properties', '.conf': 'TEXT', '.txt': 'TEXT'}
            config_type = type_map.get(ext, None)

            configs.append((group, data_id, content, config_type))
            self.logger.info('[%s@%s]  待上传: group=%s, dataId=%s (%s)',
                              self.name, self.ssh.host, group, data_id, local_path)

        # 登录 Nacos 并上传
        mgr = NacosConfigManager(logger=self.logger)
        self.logger.info('[%s@%s] Nacos 登录认证: %s', self.name, self.ssh.host, nacos_host)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for group, data_id, content, config_type in configs:
            self.logger.info('[%s@%s] 上传配置: group=%s, dataId=%s',
                              self.name, self.ssh.host, group, data_id)
            mgr.publish_config(nacos_host, data_id, content, token,
                               group=group, config_type=config_type, ssh=self.ssh)

        self.logger.info('[%s@%s] Nacos 配置上传完成，共 %d 个',
                          self.name, self.ssh.host, len(configs))

    def health_check(self):
        checker = _NacosChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
        self.logger.info('[%s@%s] Nacos 健康检查通过', self.name, self.ssh.host)

    @classmethod
    def deploy_cluster(cls, hosts, servers_map, config, context, logger, results):
        """集群部署入口：并行准备 → 数据库初始化 → 依次启动 → 健康检查 → 密码修改 → 配置上传"""
        nacos_hosts = sorted(hosts)
        results.setdefault('nacos', {})
        lock = threading.Lock()

        # 确定实际运行节点（与 _is_valid_host 逻辑一致）
        if len(nacos_hosts) == 3:
            deploy_hosts = nacos_hosts
        else:
            deploy_hosts = nacos_hosts[:1]
        logger.info('--- Nacos 部署，运行节点（按顺序）: %s ---', ', '.join(deploy_hosts))

        def _get_ssh(h):
            server_info = servers_map.get(h)
            if not server_info:
                logger.error('未找到主机 %s 的 SSH 配置', h)
                results['nacos'][h] = 'skipped'
                return None
            return get_ssh_client(server_info, dry_run=getattr(config, 'debug', False),
                                  logger=logger)

        _instances = {}

        # ── Phase 1: 所有主机并行准备（下载 + 解压 + 配置 + 清理） ──
        logger.info('--- Phase 1: 并行准备（下载/解压/配置） ---')
        prep_threads = []
        prep_lock = threading.Lock()

        def _prepare_one(host):
            ssh = _get_ssh(host)
            if not ssh:
                return
            try:
                inst = cls(ssh, config, context, logger)
                inst.prepare()
                with prep_lock:
                    _instances[host] = inst
                    results['nacos'][host] = 'prepared'
            except Exception as e:
                logger.error('[%s] Nacos 准备阶段失败: %s', host, e)
                with prep_lock:
                    results['nacos'][host] = 'failed'

        for host in deploy_hosts:
            t = threading.Thread(target=_prepare_one, args=(host,))
            prep_threads.append(t)
            t.start()
        for t in prep_threads:
            t.join()

        failed_prep = [h for h in deploy_hosts if results['nacos'].get(h) == 'failed']
        if failed_prep and getattr(config, 'fail_fast', True):
            logger.error('===== Nacos 部署因准备阶段失败中止: %s =====', ', '.join(failed_prep))
            return

        # ── Phase 2: 首台主机初始化数据库 ──
        first_host = deploy_hosts[0]
        first_inst = _instances.get(first_host)
        if first_inst and results['nacos'].get(first_host) != 'failed':
            logger.info('--- Phase 2: 首台 %s 初始化数据库 ---', first_host)
            try:
                first_inst._init_database()
            except Exception as e:
                logger.error('[%s] Nacos 数据库初始化失败: %s', first_host, e)
                results['nacos'][first_host] = 'failed'
                if getattr(config, 'fail_fast', True):
                    return

        # ── Phase 3: 各主机依次启动 ──
        logger.info('--- Phase 3: 依次启动 ---')
        for host in deploy_hosts:
            if results['nacos'].get(host) == 'failed':
                continue
            inst = _instances.get(host)
            if not inst:
                continue
            logger.info('[%s] 启动 Nacos...', host)
            try:
                inst.start_service()
                results['nacos'][host] = 'started'
            except Exception as e:
                logger.error('[%s] Nacos 启动失败: %s', host, e)
                results['nacos'][host] = 'failed'
                if getattr(config, 'fail_fast', True):
                    return

        # ── Phase 4: 所有主机启动完成后统一健康检查 ──
        run_health_checks(deploy_hosts, _instances, results, 'nacos', lock, config, logger,
                          max_retries=6, retry_interval=60,
                          post_start_delay_seconds=60)

        succeeded_hosts = [h for h, s in results.get('nacos', {}).items() if s == 'success']

        # 健康检查通过后等待 10 秒，让 Nacos 完全就绪再执行后续操作
        if succeeded_hosts:
            logger.info('[nacos] 健康检查通过，等待 10 秒后继续...')
            time.sleep(10)

        # ── Phase 5: 先修改密码（如果需要），再上传配置 ──
        nacos_password = getattr(config, 'nacos_password', '0192023A7BBD73250516F069DF18B500')
        default_nacos_password = '0192023A7BBD73250516F069DF18B500'
        if nacos_password and nacos_password != default_nacos_password and succeeded_hosts:
            first_host = succeeded_hosts[0]
            logger.info('--- Phase 5: 修改 Nacos 密码（%s -> %s） ---',
                         default_nacos_password, nacos_password)
            try:
                nacos_cfg = get_component_config(config, 'nacos')
                nacos_port = nacos_cfg.get('port', 8848)
                nacos_host = '{}:{}'.format(first_host, nacos_port)
                mgr = NacosConfigManager(logger=logger)
                mgr.change_password(nacos_host, default_nacos_password,
                                    nacos_password)
                logger.info('--- Nacos 密码修改完成 ---')
            except Exception as e:
                logger.warning('Nacos 密码修改失败: %s', e)

        # ── Phase 6: 密码修改后上传 Nacos 配置 ──
        if succeeded_hosts:
            upload_host = succeeded_hosts[0]
            upload_inst = _instances.get(upload_host)
            if upload_inst:
                logger.info('--- Phase 6: 首台 %s 上传 Nacos 配置 ---', upload_host)
                try:
                    upload_inst._upload_nacos_configs()
                except Exception as e:
                    logger.error('[%s] Nacos 配置上传失败: %s', upload_host, e)

        for host in deploy_hosts:
            inst = _instances.get(host)
            if inst:
                inst.ssh.close()

        failed = [h for h, s in results['nacos'].items() if s == 'failed']
        if failed:
            logger.warning('--- Nacos 在以下主机安装失败: %s ---', ', '.join(failed))
        else:
            logger.info('--- Nacos 部署完毕（%d 台主机）---', len(deploy_hosts))
