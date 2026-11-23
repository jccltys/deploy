# -*- coding: utf-8 -*-
"""健康检查基础框架——基类 + 通用检查函数"""
import os
import shlex

from core.ssh_client import get_ssh_client


class HealthChecker(object):
    """健康检查器基类"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None):
        self.ssh = ssh_client
        self.component_dir = component_dir
        self.config = config
        self.logger = logger

    def check(self):
        raise NotImplementedError


def check_port(ssh, host, port, timeout=60, interval=2, logger=None):
    """等待远程主机指定 TCP 端口开始监听"""
    if logger:
        logger.info('等待 %s:%d 端口就绪...', host, port)
    for _ in range(timeout // interval):
        cmd = 'bash -c "cat < /dev/null > /dev/tcp/{h}/{p}" 2>/dev/null'.format(h=host, p=port)
        if logger:
            logger.info('[health] 执行端口检查: %s', cmd)
        code, _, _ = ssh.execute(cmd)
        if code == 0:
            if logger:
                logger.info('%s:%d 已就绪', host, port)
            return True
        sleep_cmd = 'sleep {}'.format(interval)
        if logger:
            logger.info('[health] 执行命令: %s', sleep_cmd)
        ssh.execute(sleep_cmd)
    msg = '{}:{} 等待超时（{}秒）'.format(host, port, timeout)
    if logger:
        logger.warning(msg)
    raise RuntimeError(msg)


def check_process(ssh, pattern, logger=None):
    """检查进程是否存在（通过 pgrep）"""
    cmd = 'pgrep -x "{}" > /dev/null 2>&1'.format(pattern)
    if logger:
        logger.info('[health] 执行检查: %s', cmd)
    code, _, _ = ssh.execute(cmd)
    if logger:
        logger.info('[health] 进程检查返回码: %d', code)
    return code == 0


def check_cli(ssh, cmd, expected_in_output, logger=None):
    """执行 CLI 命令并检查输出是否包含预期字符串"""
    if logger:
        logger.info('[health] 执行检查: %s', cmd)
    code, out, _ = ssh.execute(cmd)
    if logger:
        logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
    if code == 0 and expected_in_output in out:
        return True
    return False


def check_zookeeper_cluster_health(zk_hosts, install_dir, config, servers_map, logger):
    """检查 ZK 集群所有节点的健康状态"""
    if not zk_hosts:
        if logger:
            logger.warning('ZK 主机列表为空，跳过集群健康检查')
        return True

    if getattr(config, 'debug', False):
        if logger:
            logger.debug('(调试模式) 跳过 ZK 集群健康检查')
        return True

    failed_nodes = []

    for host in zk_hosts:
        server_info = servers_map.get(host)
        if not server_info:
            failed_nodes.append((host, 'SSH 配置未找到'))
            continue

        ssh = None
        try:
            ssh = get_ssh_client(server_info, dry_run=False, logger=logger)

            java_home = os.path.join(install_dir, 'comms', 'java')
            zk_bin = os.path.join(install_dir, 'comms', 'zookeeper', 'bin', 'zkServer.sh')
            cmd = 'export JAVA_HOME={} && {} status 2>&1'.format(
                shlex.quote(java_home), zk_bin)

            healthy = False
            for _ in range(12):
                code, out, _ = ssh.execute(cmd)
                if code == 0 and 'Mode:' in out:
                    if logger:
                        logger.info('[%s] ZK 节点健康', host)
                    healthy = True
                    break
                if logger:
                    logger.debug('[%s] ZK 状态检查中...', host)
                ssh.execute('sleep 5')

            if not healthy:
                failed_nodes.append((host, 'ZK 节点未就绪或状态异常'))

        except Exception as e:
            if logger:
                logger.error('[%s] ZK 检查异常: %s', host, e)
            failed_nodes.append((host, str(e)))

        finally:
            if ssh:
                ssh.close()

    if failed_nodes:
        details = '; '.join('{}: {}'.format(h, e) for h, e in failed_nodes)
        raise RuntimeError('ZK 集群节点检查失败: {}'.format(details))

    return True
