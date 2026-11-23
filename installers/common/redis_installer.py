# -*- coding: utf-8 -*-
"""
Redis 安装器 — 单机部署
生成 redis.conf 到 conf/，版本化解压目录，通过 redis-server 启动
"""
import os
import re
import shlex

from installers.common.base_installer import BaseInstaller
from utils.health import RedisChecker, RedisSentinelChecker
from core.config_utils import get_component_config


class RedisInstaller(BaseInstaller):
    GROUP = 'common'
    def extract_package(self):
        """解压后将冗余目录更名为版本化名称，创建规范软链接"""
        super().extract_package()

        # 从包名解析版本化名称（去掉归档扩展名）
        versioned_name = re.sub(
            r'\.(tar\.(gz|xz|bz2)|tgz)$', '', self.package_file, flags=re.I
        )

        # 若解压目录名已经是版本化名称，说明包名和目录名一致，无需处理
        if self._extracted_basename == versioned_name:
            return

        symlink = self.component_dir

        # 重命名目录：redis/ -> redis-6.2.6-250608-Linux.x86_64
        old_path = self._extracted_path
        new_path = os.path.join(self.comms_dir, versioned_name)
        self.logger.info('[%s@%s] 重命名 %s -> %s',
                         self.name, self.ssh.host, self._extracted_basename, versioned_name)
        self.ssh.execute('mv {} {}'.format(shlex.quote(old_path), shlex.quote(new_path)))

        # 创建软链接指向版本化目录
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(versioned_name), shlex.quote(symlink)))

        # 更新记录
        self._extracted_basename = versioned_name
        self._extracted_path = new_path

    def _get_redis_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('redis', []))

    def _is_sentinel_mode(self):
        return len(self._get_redis_hosts()) == 3

    def _is_master(self):
        hosts = self._get_redis_hosts()
        return len(hosts) == 0 or self.ssh.host == hosts[0]

    def template_vars(self, **overrides):
        vars = super().template_vars(**overrides)
        redis_cfg = get_component_config(self.config, 'redis')
        redis_port = redis_cfg.get('port', 6379)
        vars['redis_port'] = redis_port
        sentinel_port = redis_cfg.get('sentinel_port', 26379)
        vars['sentinel_port'] = sentinel_port
        vars['sentinel_name'] = redis_cfg.get('sentinel_name', 'mymaster')
        vars['redis_password'] = redis_cfg.get('password', 'Redis@123')
        if self._is_sentinel_mode():
            hosts = self._get_redis_hosts()
            master_host = hosts[0]
            if not self._is_master():
                vars['replicaof'] = 'replicaof {} {}'.format(master_host, redis_port)
            else:
                vars['replicaof'] = ''
            vars['master_host'] = master_host
        else:
            vars['replicaof'] = ''
        return vars

    def start_service(self):
        self.logger.info('[%s@%s] 启动 Redis', self.name, self.ssh.host)
        if self.config.debug:
            self.logger.info('调试模式：跳过 Redis 启动')
            return
        cd = shlex.quote(self.component_dir)
        redis_cfg = get_component_config(self.config, 'redis')
        port = redis_cfg.get('port', 6379)
        password = redis_cfg.get('password', 'Redis@123')
        unit = '''[Unit]
Description=Redis
After=network.target

[Service]
Type=simple
ExecStart={cd}/bin/redis-server {cd}/conf/redis.conf --daemonize no
ExecStop={cd}/bin/redis-cli -p {port} -a {password} shutdown
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(cd=cd, port=port, password=password)
        self._create_systemd_unit('redis', unit)
        if self._use_systemd:
            self._enable_systemd_unit('redis', start=True)
        else:
            self._script_start('{}/bin/redis-server {}/conf/redis.conf > /dev/null 2>&1 &'.format(cd, cd))
        if self._is_sentinel_mode():
            sentinel_unit = '''[Unit]
Description=Redis Sentinel
After=network.target

[Service]
Type=simple
ExecStart={cd}/bin/redis-server {cd}/conf/sentinel.conf --sentinel --daemonize no
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(cd=cd)
            self._create_systemd_unit('redis-sentinel', sentinel_unit)
            if self._use_systemd:
                self._enable_systemd_unit('redis-sentinel', start=True)
            else:
                self._script_start('{}/bin/redis-server {}/conf/sentinel.conf --sentinel > /dev/null 2>&1 &'.format(cd, cd))
            self.logger.info('[%s] Sentinel 已启动', self.ssh.host)

    def health_check(self):
        redis_cfg = get_component_config(self.config, 'redis')
        redis_password = redis_cfg.get('password', 'Redis@123')
        RedisChecker(self.ssh, self.component_dir, self.config, self.logger,
                     password=redis_password).check()
        if self._is_sentinel_mode():
            RedisSentinelChecker(self.ssh, self.component_dir, self.config, self.logger).check()
        self.logger.info('[%s@%s] Redis 健康检查通过', self.name, self.ssh.host)
