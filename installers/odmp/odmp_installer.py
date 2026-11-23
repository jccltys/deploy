# -*- coding: utf-8 -*-
"""ODMP 组件安装器"""
import os
import posixpath
import shlex
import time
import yaml

from installers.common.base_installer import BaseInstaller
from tools.odmp_api import IngestionFlow, ImportFlow
from core.config_utils import get_odmp_vars, get_component_config, get_zookeeper_vars
from tools.nacos_api import NacosConfigManager


class OdmpInstaller(BaseInstaller):
    GROUP = 'odmp'
    PACKAGE_NAME = 'jax-super-all'
    REQUIRES_HADOOP_CONF = True

    @classmethod
    def post_deploy(cls, hosts, instances, servers_map, config, context, logger, results, failed):
        """ODMP 后置初始化：_run_odmp_api 是全局初始化，单机/多机都只跑一次"""
        if not instances or failed:
            return
        inst = next(iter(instances.values()))
        try:
            inst._run_odmp_api()
        except Exception as e:
            logger.warning('[odmp_api] 初始化异常: %s', e)

    @property
    def component_dir(self):
        return self._apps_component_symlink()

    @property
    def _package_dest_dir(self):
        return self.apps_root

    def _extract_version_rename(self, extracted_basename, extracted_path):
        pkg_version = self._extract_version_from_package(self.package_file)
        if pkg_version and not extracted_basename.endswith(pkg_version):
            versioned_name = '{}-{}'.format(extracted_basename, pkg_version)
            self.logger.info('[%s@%s] 重命名解压目录: %s -> %s',
                              self.name, self.ssh.host,
                              extracted_basename, versioned_name)
            self.ssh.execute('mv {} {}'.format(
                shlex.quote(extracted_path),
                shlex.quote(posixpath.join(self.apps_root, versioned_name))))
            return versioned_name, posixpath.join(self.apps_root, versioned_name)
        return None

    def _create_dirs(self):
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.apps_root)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.apps_root)))

    @classmethod
    def get_template_vars_doc(cls):
        base = super(OdmpInstaller, cls).get_template_vars_doc()
        base.update(cls._app_common_template_vars_doc())
        return base

    def template_vars(self, **overrides):
        odmp_vars = get_odmp_vars(self.ctx, self.config) or {}
        self._with_common_app_vars(overrides, odmp_vars)
        return super().template_vars(**overrides)

    @property
    def _hadoop_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('hadoop', []))

    def _hadoop_conf_dir(self):
        return os.path.join(self.comms_dir, 'hadoop', 'etc', 'hadoop')

    def _copy_hadoop_configs(self):
        hadoop_hosts = self._hadoop_hosts
        if not hadoop_hosts:
            self.logger.warning('[%s@%s] 未发现 Hadoop 主机，跳过配置拷贝',
                                self.name, self.ssh.host)
            return

        target_dir = os.path.join(self.component_dir, 'hadoop', 'etc')
        self.logger.info('[%s@%s] 从部署机器 HTTP 服务下载 Hadoop 全量配置到 %s',
                          self.name, self.ssh.host, target_dir)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(target_dir)))

        base_url = 'http://{}:{}/hadoop'.format(self.config.host_ip, self.config.http_port)
        # 下载 tar.gz 包后解压（包含 hadoop 目录下所有文件）
        tar_url = '{}/hadoop-conf.tar.gz'.format(base_url)
        tar_local = '/tmp/hadoop-conf.tar.gz'
        self.ssh.execute(
            'curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
                shlex.quote(tar_local), tar_url), check=False)
        self.ssh.execute(
            'tar -xzf {} -C {}'.format(
                shlex.quote(tar_local), shlex.quote(target_dir)), check=False)
        self.ssh.execute('rm -f {}'.format(shlex.quote(tar_local)))
        self.logger.info('[%s@%s] Hadoop 全量配置拷贝完成', self.name, self.ssh.host)

    def prepare(self):
        self.logger.info('[%s@%s] === 开始准备（下载 + 解压 + 配置修改）===',
                         self.name, self.ssh.host)
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._copy_hadoop_configs()
        self._patch_config_files()
        self._cleanup_package()
        self.logger.info('[%s@%s] === 准备完成 ===', self.name, self.ssh.host)

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 ODMP 组件 ===', self.name, self.ssh.host)
        self.prepare()
        self._init_database()
        self.start_service()
        if not skip_health_check:
            self.logger.info('[%s@%s] 等待 3 分钟后开始健康检查...', self.name, self.ssh.host)
            time.sleep(180)
            self.health_check()
            self._run_odmp_api()
        self.logger.info('[%s@%s] === ODMP 组件安装完成 ===', self.name, self.ssh.host)

    def _run_odmp_api(self):
        """服务健康后调用 odmp_api 执行完整初始化（IngestionFlow + ImportFlow，后者内部自动串联 ConfigFlow / DataProcessUpdateFlow / JobUpdateFlow）"""
        odmp_cfg = get_component_config(self.config, 'odmp')
        port = odmp_cfg.get('port', 9900)
        api_addr = '{}:{}'.format(self.ssh.host, port)
        pkg_dir = getattr(self.config, 'package_dir', '') or os.getcwd()
        import_dir = os.path.join(os.getcwd(), 'lib/odmp/')

        self.logger.info('[odmp_api] 开始初始化: api=%s pkg_dir=%s', api_addr, pkg_dir)

        # 第一步：采集层初始化（数据中心/注册中心/数据源/集群/算子包）
        try:
            flow = IngestionFlow(api_addr)
            flow.run(package_dir=pkg_dir, logger=self.logger)
        except RuntimeError as e:
            self.logger.warning('[odmp_api] ingestion 初始化异常: %s', e)
        else:
            self.logger.info('[odmp_api] ingestion 初始化完成')

        # 第二步：Excel 导入（自动执行：dataDomain → 关联数据域 → 系统配置 → 其余类型 → 发布）
        zk_vars = get_zookeeper_vars(self.ctx, self.config)
        zk_connect = zk_vars.get('zookeeper_servers') if zk_vars else None
        if os.path.isdir(import_dir):
            self.logger.info('[odmp_api] 开始 Excel 导入: import_dir=%s', import_dir)
            try:
                flow = ImportFlow(api_addr)
                flow.run(import_dir=import_dir, logger=self.logger, zk_connect=zk_connect)
            except RuntimeError as e:
                self.logger.warning('[odmp_api] import 异常: %s', e)
            else:
                self.logger.info('[odmp_api] Excel 导入完成')
        else:
            self.logger.info('[odmp_api] 未找到导入目录 %s，跳过 Excel 导入', import_dir)

    def _odmp_vars(self):
        return get_odmp_vars(self.ctx, self.config) or {}

    def _patch_config_files(self):
        odmp_vars = self._odmp_vars()
        nacos_host = odmp_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_user = odmp_vars.get('nacos_user', 'nacos')
        nacos_password = odmp_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')
        mysql_host = odmp_vars.get('mysql_host', '127.0.0.1')
        mysql_port = odmp_vars.get('mysql_port', '3306')
        mysql_user = odmp_vars.get('mysql_user', 'root')
        mysql_password = odmp_vars.get('mysql_password', 'MySQL@123')
        mysql_address = '{}:{}'.format(mysql_host, mysql_port)

        def _patch_file(rel_path):
            full_path = os.path.join(self.component_dir, rel_path)
            code, content, _ = self.ssh.execute(
                'cat {} 2>/dev/null'.format(shlex.quote(full_path)))
            if code != 0:
                self.logger.warning('[%s@%s] 未找到 %s，跳过修改',
                                    self.name, self.ssh.host, rel_path)
                return

            # 用 yaml 解析配置文件结构，获取各键的当前值
            data = yaml.safe_load(content)

            nacos = data.get('spring', {}).get('cloud', {}).get('nacos', {})
            discovery = nacos.get('discovery', {})
            config_center = nacos.get('config', {})
            datasource = data.get('spring', {}).get('datasource', {})
            jax = data.get('jax', {})
            security = jax.get('security', {})
            debug = jax.get('debug', {})

            # 用 yaml 读到的原始值做精确替换，不丢失注释和格式
            line_replacements = [
                # Nacos discovery
                ('        enabled: {}'.format(str(discovery.get('enabled', False)).lower()),
                 '        enabled: true'),
                ('        server-addr: {}'.format(discovery.get('server-addr', 'localhost:8848')),
                 '        server-addr: {}'.format(nacos_host)),
                ('        username: {}'.format(discovery.get('username', 'nacos')),
                 '        username: {}'.format(nacos_user)),
                ('        password: {}'.format(discovery.get('password', 'nacos')),
                 '        password: {}'.format(nacos_password)),

                # Nacos config center
                ('        server-addr: {}'.format(config_center.get('server-addr', 'localhost:8848')),
                 '        server-addr: {}'.format(nacos_host)),
                ('        username: {}'.format(config_center.get('username', 'nacos')),
                 '        username: {}'.format(nacos_user)),
                ('        password: {}'.format(config_center.get('password', 'nacos')),
                 '        password: {}'.format(nacos_password)),

                # MySQL datasource
                ('    url: {}'.format(datasource.get('url', '')),
                 '    url: jdbc:mysql://{}/odmp?characterEncoding=utf8&useSSL=false&allowMultiQueries=true&serverTimezone=Asia/Shanghai'.format(mysql_address)),
                ('    username: {}'.format(datasource.get('username', 'root')),
                 '    username: {}'.format(mysql_user)),
                ('    password: {}'.format(datasource.get('password', 'MySQL@123')),
                 '    password: {}'.format(mysql_password)),

                # Python environment
                ('    pythonEnv: {}'.format(debug.get('pythonEnv', '/home/python_venv')),
                 '    pythonEnv: {}'.format(os.path.join(self.install_dir, 'apps/odmp/pyenv'))),

            ]

            for old, new in line_replacements:
                if old != new:
                    content = content.replace(old, new)

            self.write_remote_file(full_path, content)
            self.logger.info('[%s@%s] 已更新: %s',
                              self.name, self.ssh.host, rel_path)

        _patch_file('jax/application.yml')

    def _init_database(self):
        odmp_vars = self._odmp_vars()
        self._init_app_database(odmp_vars, 'odmp')

    def start_service(self):
        self.logger.info('[%s@%s] 启动 ODMP 服务', self.name, self.ssh.host)
        start_script = os.path.join(self.component_dir, 'start.sh')
        code, _, _ = self.ssh.execute(
            'test -f {}'.format(shlex.quote(start_script)))
        if code == 0:
            self.logger.info('[%s@%s] 创建 systemd unit, 启动脚本: start.sh',
                              self.name, self.ssh.host)
            stop_script = os.path.join(self.component_dir, 'stop.sh')
            unit_content = '''[Unit]
Description=ODMP
After=network.target

[Service]
Type=forking
Environment=JAVA_HOME={java_home}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:{java_home}/bin
ExecStart={script}
ExecStop={stop_script}
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target'''.format(
                    java_home=shlex.quote(self.java_home),
                    script=shlex.quote(start_script),
                    stop_script=shlex.quote(stop_script))
            self._create_systemd_unit('odmp', unit_content)
            if self._use_systemd:
                self._enable_systemd_unit('odmp', start=True)
                self.logger.info('[%s@%s] ODMP 服务已通过 systemd 启动',
                                  self.name, self.ssh.host)
            else:
                self._script_start(
                    'nohup bash -c "export JAVA_HOME={} && bash {}" > /dev/null 2>&1 &'.format(
                        shlex.quote(self.java_home), shlex.quote(start_script)))
            return

        self.logger.warning('[%s@%s] 未找到 start.sh，请手动启动',
                            self.name, self.ssh.host)

    def health_check(self):
        odmp_cfg = get_component_config(self.config, 'odmp')
        port = odmp_cfg.get('port', 9900)

        self.logger.info('[%s@%s] 健康检查: 端口 %d',
                          self.name, self.ssh.host, port)

        # 1. Port check
        if not self.wait_for_port(self.ssh.host, port, timeout=60, interval=5):
            raise RuntimeError(
                '[{}@{}] ODMP 健康检查失败: 端口 {} 未就绪'
                .format(self.name, self.ssh.host, port))

        self.logger.info('[%s@%s] 端口检查通过，开始 Nacos 注册检查',
                          self.name, self.ssh.host)

        # 2. Nacos registration check
        odmp_vars = self._odmp_vars()
        nacos_host = odmp_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_user = odmp_vars.get('nacos_user', 'nacos')
        nacos_password = odmp_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('odmp',):
            try:
                mgr.check_service_registration(
                    nacos_host, service_name, token, ssh=self.ssh)
            except RuntimeError as e:
                raise RuntimeError(
                    '[{}@{}] ODMP 健康检查失败: {}'
                    .format(self.name, self.ssh.host, e))

        self.logger.info('[%s@%s] ODMP 健康检查通过（端口就绪 + Nacos 注册正常）',
                          self.name, self.ssh.host)
