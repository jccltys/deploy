# -*- coding: utf-8 -*-
import os
import posixpath
import shlex

from installers.common.base_installer import BaseInstaller
from core.config_utils import get_sso_vars, get_component_config
from tools.nacos_api import NacosConfigManager
from utils.update_spring_config import SpringConfigUpdater


class SsoInstaller(BaseInstaller):
    GROUP = 'sso'
    PACKAGE_NAME = 'unified-authentication'

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
        base = super(SsoInstaller, cls).get_template_vars_doc()
        base.update(cls._app_common_template_vars_doc())
        return base

    def template_vars(self, **overrides):
        sso_vars = get_sso_vars(self.ctx, self.config) or {}
        self._with_common_app_vars(overrides, sso_vars)
        overrides.setdefault('nacos_servers', sso_vars.get('nacos_servers', '127.0.0.1:8848'))
        return super().template_vars(**overrides)

    def prepare(self):
        self.logger.info('[%s@%s] === 开始准备（下载 + 解压 + 配置修改）===',
                         self.name, self.ssh.host)
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._patch_config_files()
        self._cleanup_package()
        self.logger.info('[%s@%s] === 准备完成 ===', self.name, self.ssh.host)

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 SSO 组件 ===', self.name, self.ssh.host)
        self.prepare()
        self._upload_nacos_configs()
        self._init_database()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self.logger.info('[%s@%s] === SSO 组件安装完成 ===', self.name, self.ssh.host)

    def _patch_config_files(self):
        sso_vars = get_sso_vars(self.ctx, self.config) or {}
        nacos_host = sso_vars.get('nacos_host', '127.0.0.1:8848')
        nacos_servers = sso_vars.get('nacos_servers', nacos_host)
        nacos_user = sso_vars.get('nacos_user', 'nacos')
        nacos_password = sso_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')
        mysql_host = sso_vars.get('mysql_host', '127.0.0.1')
        mysql_port = sso_vars.get('mysql_port', '3306')
        mysql_user = sso_vars.get('mysql_user', 'root')
        mysql_password = sso_vars.get('mysql_password', 'MySQL@123')
        mysql_address = '{}:{}'.format(mysql_host, mysql_port)

        def _patch_file(rel_path, replacements):
            full_path = os.path.join(self.component_dir, rel_path)
            code, content, _ = self.ssh.execute(
                'cat {} 2>/dev/null'.format(shlex.quote(full_path)))
            if code != 0:
                self.logger.warning('[%s@%s] 未找到 %s，跳过修改',
                                    self.name, self.ssh.host, rel_path)
                return
            patched = SpringConfigUpdater.batch_replace(content, replacements, inline=True)
            self.write_remote_file(full_path, patched)
            self.logger.info('[%s@%s] 已更新: %s',
                              self.name, self.ssh.host, rel_path)

        bootstrap_replaces = {
            'NACOS_HOST': nacos_servers,
            'NACOS_USER': nacos_user,
            'NACOS_PASSWORD': nacos_password,
            'NACOS_NAMESPACE': '${NACOS_NAMESPACE:}',
        }
        _patch_file('authentication/config/bootstrap.properties', bootstrap_replaces)
        _patch_file('gateway/config/bootstrap.properties', bootstrap_replaces)

        app_common_replaces = {
            'NACOS_HOST': nacos_servers,
            'NACOS_USER': nacos_user,
            'NACOS_PASSWORD': nacos_password,
            'FLYWAY_SQL_ENABLED': 'true',
            'MYSQL_HOST': mysql_address,
            'MYSQL_USER': mysql_user,
            'MYSQL_PASSWORD': mysql_password,
        }
        auth_replaces = dict(app_common_replaces)
        auth_replaces['MYSQL_DB'] = 'authentication'
        _patch_file('authentication/config/application.properties', auth_replaces)

        gw_replaces = dict(app_common_replaces)
        gw_replaces['MYSQL_DB'] = 'gateway'
        _patch_file('gateway/config/application.properties', gw_replaces)

    def _init_database(self):
        sso_vars = get_sso_vars(self.ctx, self.config) or {}
        self._init_app_database(sso_vars, ('authentication', 'gateway'))

    def _get_nacos_host(self):
        sso_vars = get_sso_vars(self.ctx, self.config) or {}
        return sso_vars.get('nacos_host', '127.0.0.1:8848')

    def _get_nacos_credential(self):
        sso_vars = get_sso_vars(self.ctx, self.config) or {}
        return sso_vars.get('nacos_user', 'nacos'), sso_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500')

    def _upload_nacos_configs(self):
        nacos_host = self._get_nacos_host()
        nacos_user, nacos_password = self._get_nacos_credential()
        mgr = NacosConfigManager(logger=self.logger)

        self.logger.info('[%s@%s] Nacos 登录认证', self.name, self.ssh.host)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('authentication', 'gateway'):
            config_path = os.path.join(
                self.component_dir, service_name, 'config', 'application.properties')
            code, content, err = self.ssh.execute(
                'cat {}'.format(shlex.quote(config_path)))
            if code != 0:
                self.logger.warning(
                    '[%s@%s] 未找到 %s 的 application.properties，跳过 Nacos 上传',
                    self.name, self.ssh.host, service_name)
                continue

            data_id = '{}.properties'.format(service_name)
            self.logger.info('[%s@%s] 上传 %s 到 Nacos (dataId=%s)',
                             self.name, self.ssh.host, service_name, data_id)
            mgr.publish_config(nacos_host, data_id, content, token,
                               config_type='Properties', ssh=self.ssh)

    def start_service(self):
        self.logger.info('[%s@%s] 启动 SSO 服务', self.name, self.ssh.host)
        for candidate in ('restart-all.sh', 'bin/startup.sh', 'bin/start-all.sh'):
            script = os.path.join(self.component_dir, candidate)
            code, _, _ = self.ssh.execute(
                'test -f {}'.format(shlex.quote(script)))
            if code == 0:
                self.logger.info('[%s@%s] 创建 systemd unit, 启动脚本: %s',
                                  self.name, self.ssh.host, candidate)
                unit_content = '''[Unit]
Description=SSO - Unified Authentication
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
                    java_home=shlex.quote(self.java_home),
                    script=shlex.quote(script))
                self._create_systemd_unit('sso', unit_content)
                if self._use_systemd:
                    self._enable_systemd_unit('sso', start=True)
                else:
                    self._script_start(
                        'nohup bash -c "export JAVA_HOME={} && bash {}" > /dev/null 2>&1 &'.format(
                            shlex.quote(self.java_home), shlex.quote(script)))
                return

        self.logger.warning('[%s@%s] 未找到可执行启动脚本，请手动启动',
                            self.name, self.ssh.host)

    def health_check(self):
        sso_cfg = get_component_config(self.config, 'sso')
        auth_port = sso_cfg.get('authentication_port', 9912)
        gw_port = sso_cfg.get('gateway_port', 8080)

        self.logger.info('[%s@%s] 健康检查: authentication 端口 %d, gateway 端口 %d',
                         self.name, self.ssh.host, auth_port, gw_port)

        # 1. Port check — fail fast on first failure
        for port, label in [(auth_port, 'authentication'), (gw_port, 'gateway')]:
            if not self.wait_for_port(self.ssh.host, port, timeout=60, interval=5):
                raise RuntimeError(
                    '[{}@{}] SSO 健康检查失败: {} 端口 {} 未就绪'
                    .format(self.name, self.ssh.host, label, port))

        self.logger.info('[%s@%s] 端口检查通过，开始 Nacos 注册检查',
                         self.name, self.ssh.host)

        # 2. Nacos registration check — independent login
        nacos_host = self._get_nacos_host()
        nacos_user, nacos_password = self._get_nacos_credential()
        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('authentication', 'gateway'):
            try:
                mgr.check_service_registration(
                    nacos_host, service_name, token, ssh=self.ssh)
            except RuntimeError as e:
                raise RuntimeError(
                    '[{}@{}] SSO 健康检查失败: {}'
                    .format(self.name, self.ssh.host, e))

        self.logger.info('[%s@%s] SSO 健康检查通过（端口就绪 + Nacos 注册正常）',
                         self.name, self.ssh.host)
