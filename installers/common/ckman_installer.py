# -*- coding: utf-8 -*-
"""
ckman 安装器 — 预编译二进制包
解压后产生 ckman/ 目录，重命名为版本化目录（如 ckman-v3.3.3-250727.Linux.amd64）
配置文件渲染到 conf/ 子目录，启动命令为 bin/start（自带 -d daemonize）
"""
import os
import re
import shlex

from core.config_utils import get_nacos_vars, get_ckman_vars
from installers.common.base_installer import BaseInstaller
from utils.health import CkmanChecker


class CkmanInstaller(BaseInstaller):
    GROUP = 'common'
    def extract_package(self):
        """解压后重命名为版本化目录"""
        # 先按基类逻辑解压并检测新增目录（基类会创建 comms/ckman -> ckman）
        super().extract_package()

        # 从包名解析版本化名称（去掉归档扩展名）
        versioned_name = re.sub(
            r'\.(tar\.(gz|xz|bz2)|tgz)$', '', self.package_file, flags=re.I
        )

        symlink = self.component_dir

        # 重命名目录：ckman -> ckman-v3.3.3-250727.Linux.amd64
        old_path = self._extracted_path
        new_path = os.path.join(self.comms_dir, versioned_name)
        self.logger.info('[%s@%s] 重命名 %s -> %s',
                         self.name, self.ssh.host, self._extracted_basename, versioned_name)
        self.ssh.execute('mv {} {}'.format(shlex.quote(old_path), shlex.quote(new_path)))

        # 重新创建软链接指向版本化目录
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(versioned_name), shlex.quote(symlink)))

        # 清理包自带的 ckman -> ckman 自引用软链接
        self.ssh.execute(
            'rm -f {}'.format(shlex.quote(os.path.join(new_path, 'ckman')))
        )

        # 更新记录
        self._extracted_basename = versioned_name
        self._extracted_path = new_path

    def template_vars(self, **overrides):
        ckman_vars = get_ckman_vars(self.ctx, self.config)
        if ckman_vars:
            overrides.setdefault('ckman_port', ckman_vars['ckman_port'])
        nacos_cfg = get_nacos_vars(self.ctx, self.config)
        if nacos_cfg:
            overrides.setdefault('nacos_enabled', nacos_cfg['nacos_enabled'])
            overrides.setdefault('nacos_hosts',
                                 ',\n      '.join('"{}"'.format(h)
                                                for h in nacos_cfg['nacos_hosts']))
            overrides.setdefault('nacos_servers', nacos_cfg['nacos_servers'])
            overrides.setdefault('nacos_port', nacos_cfg['nacos_port'])
            overrides.setdefault('nacos_user', nacos_cfg['nacos_user'])
            overrides.setdefault('nacos_password', nacos_cfg['nacos_password'])
        else:
            overrides.setdefault('nacos_enabled', 'false')
        return super().template_vars(**overrides)

    def start_service(self):
        self.logger.info('[%s@%s] 启动 ckman', self.name, self.ssh.host)
        cd = shlex.quote(self.component_dir)
        unit = '''[Unit]
Description=ckman - ClickHouse Manager
After=network.target

[Service]
Type=forking
ExecStart={cd}/bin/start
ExecStop={cd}/stop
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(cd=cd)
        self._create_systemd_unit('ckman', unit)
        if self._use_systemd:
            self._enable_systemd_unit('ckman', start=True)
        else:
            self._script_start('{}/bin/start'.format(cd))

    def health_check(self):
        checker = CkmanChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
        self.logger.info('[%s@%s] ckman 健康检查通过', self.name, self.ssh.host)
