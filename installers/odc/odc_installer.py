# -*- coding: utf-8 -*-
"""ODC 组件安装器 — 骨架实现"""
import os
import shlex

from installers.common.base_installer import BaseInstaller


class OdcInstaller(BaseInstaller):
    GROUP = 'odc'

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 ODC 组件 ===', self.name, self.ssh.host)
        self._create_dirs()
        self.logger.info('[%s@%s] ODC 组件安装完成（骨架，待实现完整安装逻辑）',
                         self.name, self.ssh.host)
