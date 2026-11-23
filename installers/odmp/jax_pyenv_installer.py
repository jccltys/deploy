# -*- coding: utf-8 -*-
"""jax-pyenv Python 虚拟环境安装器"""
import os
import shlex

from installers.common.base_installer import BaseInstaller


class JaxPyenvInstaller(BaseInstaller):
    GROUP = 'odmp'
    COMPONENT_NAME = 'jax-pyenv'
    PACKAGE_NAME = 'jax-pyenv'

    @property
    def apps_root(self):
        return os.path.join(self.config.apps_dir, 'odmp')

    @property
    def component_dir(self):
        """软链接路径: apps/odmp/pyenv"""
        return os.path.join(self.apps_root, 'pyenv')

    @property
    def _package_dest_dir(self):
        return self.apps_root

    def _create_dirs(self):
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.apps_root)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.apps_root)))

    def prepare(self):
        self.logger.info('[%s@%s] === 开始准备（下载 + 解压）===',
                          self.name, self.ssh.host)
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._cleanup_package()
        self.logger.info('[%s@%s] === 准备完成 ===', self.name, self.ssh.host)
