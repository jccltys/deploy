# -*- coding: utf-8 -*-
"""
SSH 客户端模块 — 基于系统 ssh 命令（subprocess），不依赖 paramiko
支持密钥认证，调试模式下仅打印不执行
每次请求建立独立 TCP 连接（不复用 ControlMaster），避免 socket 残留导致卡死
"""
import os
import subprocess


class SSHClient(object):
    """SSH 远程执行客户端"""

    def __init__(self, host, port=22, username='root', key_file=None,
                 dry_run=False, logger=None):
        self.host = host
        self.port = port
        self.username = username
        self.key_file = key_file
        self.dry_run = dry_run
        self.logger = logger

    def _build_base_cmd(self):
        cmd = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=10',
            '-o', 'BatchMode=yes',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'TCPKeepAlive=yes',
            '-o', 'LogLevel=QUIET',
        ]
        if self.port != 22:
            cmd.extend(['-p', str(self.port)])
        if self.key_file:
            cmd.extend(['-i', os.path.expanduser(self.key_file)])
        return cmd

    def execute(self, command, timeout=300, check=False, log_command=True,
               background=False):
        if self.logger and log_command:
            truncated = command[:300] + ('...' if len(command) > 300 else '')
            self.logger.info('[%s] 执行命令: %s', self.host, truncated)

        if self.dry_run:
            if self.logger:
                self.logger.info('[%s] (调试模式) 跳过执行', self.host)
            return 0, '', ''

        cmd = self._build_base_cmd()
        cmd.append('{}@{}'.format(self.username, self.host))
        cmd.append(command)

        if background:
            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                return 0, '', ''
            except FileNotFoundError:
                if self.logger:
                    self.logger.error('[%s] 未找到 ssh 命令', self.host)
                raise RuntimeError('[{}] 系统未安装 ssh'.format(self.host))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=timeout
            )
            if self.logger:
                self.logger.info('[%s] 返回码: %d', self.host, result.returncode)
                if result.stdout:
                    self.logger.info('[%s] stdout: %s', self.host,
                                      result.stdout.strip()[:200])
                if result.stderr:
                    self.logger.info('[%s] stderr: %s', self.host,
                                      result.stderr.strip()[:200])
            if check and result.returncode != 0:
                msg = '[{}] 命令执行失败 (code={}): {}'.format(
                    self.host, result.returncode, command[:120])
                raise RuntimeError(msg)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            if self.logger:
                self.logger.error('[%s] 命令超时: %s', self.host, command[:100])
            raise RuntimeError('[{}] 命令超时: {}'.format(self.host, command[:100]))
        except FileNotFoundError:
            if self.logger:
                self.logger.error('[%s] 未找到 ssh 命令', self.host)
            raise RuntimeError('[{}] 系统未安装 ssh'.format(self.host))

    def close(self):
        pass


def get_ssh_client(server_info, dry_run=False, logger=None):
    return SSHClient(
        host=server_info['host'],
        port=server_info.get('port', 22),
        username=server_info.get('username', 'root'),
        key_file=server_info.get('key_file'),
        dry_run=dry_run,
        logger=logger,
    )
