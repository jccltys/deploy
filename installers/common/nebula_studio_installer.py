# -*- coding: utf-8 -*-
"""Nebula Studio 安装器 — 仅支持 1 台主机部署

解压后直接 ./server 启动，无需修改配置文件。
"""
import shlex

from installers.common.base_installer import BaseInstaller
from utils.health import NebulaStudioChecker
from core.config_utils import get_nebula_studio_vars


class NebulaStudioInstaller(BaseInstaller):
    GROUP = 'common'
    COMPONENT_NAME = 'nebula_studio'
    PACKAGE_NAME = 'nebula-graph-studio'

    @property
    def studio_port(self):
        nv = get_nebula_studio_vars(self.config)
        return nv.get('nebula_studio_port', 7001)

    def start_service(self):
        self.logger.info('[%s@%s] 启动 Nebula Studio', self.name, self.ssh.host)
        if self.config.debug:
            self.logger.info('调试模式：跳过 Nebula Studio 启动')
            return
        comp_q = shlex.quote(self.component_dir)
        unit_content = '''[Unit]
Description=Nebula Studio
After=network.target

[Service]
Type=simple
WorkingDirectory={comp_q}
ExecStart={comp_q}/server
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target'''.format(comp_q=comp_q)
        self._create_systemd_unit('nebula-studio', unit_content)
        if self._use_systemd:
            self._enable_systemd_unit('nebula-studio', start=True)
        else:
            self._script_start('cd {} && nohup ./server > /dev/null 2>&1 </dev/null &'.format(comp_q))

    def health_check(self):
        NebulaStudioChecker(
            self.ssh, self.component_dir, self.config, self.logger
        ).check()
        self.logger.info('[%s@%s] Nebula Studio 健康检查通过',
                         self.name, self.ssh.host)
