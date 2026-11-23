# -*- coding: utf-8 -*-
"""
Java 11 额外版本安装器
继承 JavaInstaller，安装到 {comms}/java11，不覆盖默认 JAVA_HOME
"""
import os

from installers.common.java_installer import JavaInstaller


class Java11Installer(JavaInstaller):
    GROUP = 'common'
    @property
    def component_dir(self):
        return os.path.join(self.comms_dir, 'java11')

    def render_configs(self):
        self.logger.info('[%s@%s] 额外 JDK 版本，不修改默认 JAVA_HOME', self.name, self.ssh.host)

    def start_service(self):
        self.logger.info('[%s@%s] 无需启动服务', self.name, self.ssh.host)
