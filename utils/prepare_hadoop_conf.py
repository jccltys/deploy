# -*- coding: utf-8 -*-
"""
Hadoop 配置预处理工具

从 Hadoop 第一台主机 scp 配置文件到部署机器的包目录下，
供 ODMP / DolphinScheduler 等组件通过部署机器 HTTP 服务下载。
"""
import argparse
import logging
import os
import subprocess
import sys


def prepare_hadoop_conf(comp_hosts, servers_map, package_dir, install_dir, logger=None):
    hadoop_hosts = comp_hosts.get('hadoop', [])
    if not hadoop_hosts:
        if logger:
            logger.info('未发现 Hadoop 主机，跳过配置预处理')
        return

    hadoop_conf_local = os.path.join(package_dir, 'hadoop')
    os.makedirs(hadoop_conf_local, exist_ok=True)

    hadoop_host = sorted(hadoop_hosts)[0]
    server_info = servers_map.get(hadoop_host)
    if not server_info:
        if logger:
            logger.warning('未找到 Hadoop 主机 %s 的 SSH 配置', hadoop_host)
        return

    ssh_user = server_info.get('username', 'root')
    ssh_port = server_info.get('port', 22)
    hadoop_conf_remote = os.path.join(install_dir, 'comms', 'hadoop', 'etc', 'hadoop')

    if logger:
        logger.info('从 %s@%s:%s 拷贝 Hadoop 配置到 %s',
                    ssh_user, hadoop_host, hadoop_conf_remote, hadoop_conf_local)

    _scp_opts = [
        'scp',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'BatchMode=yes',
        '-o', 'PasswordAuthentication=no',
        '-o', 'ConnectTimeout=10',
        '-P', str(ssh_port),
    ]

    try:
        result = subprocess.run(
            _scp_opts + [
                '-r', '{}@{}:{}/.'.format(ssh_user, hadoop_host, hadoop_conf_remote),
                hadoop_conf_local,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()[:300] if result.stderr else ''
            if logger:
                logger.error('SCP 拷贝 Hadoop 配置失败 (rc=%d): %s',
                             result.returncode, stderr)
            return

        files = os.listdir(hadoop_conf_local)
        if logger:
            logger.info('Hadoop 配置文件已就绪（共 %d 个文件）: %s',
                        len(files), ', '.join(files))

        # 打成 tar.gz 包，供 odmp 等组件一次性下载
        tar_path = os.path.join(hadoop_conf_local, 'hadoop-conf.tar.gz')
        # tar 归档 '.' 时 macOS BSD tar 会因读取目录元数据变化返回 rc=1，
        # 但归档本身已完成且可用，仅在 rc>=2 时才算真正失败
        result = subprocess.run([
            'tar', '-czf', tar_path, '-C', hadoop_conf_local, '.',
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode >= 2:
            stderr = result.stderr.strip()[:200] if result.stderr else ''
            if logger:
                logger.warning('Hadoop 配置打包失败 (rc=%d): %s',
                               result.returncode, stderr)
        else:
            msg = ('Hadoop 配置打包完成（rc=1，非致命警告）' if result.returncode == 1
                   else 'Hadoop 配置打包完成')
            if logger:
                logger.info('%s: %s（共 %d 个文件）', msg, tar_path, len(files))
    except subprocess.TimeoutExpired:
        if logger:
            logger.error('SCP 拷贝 Hadoop 配置超时 (120s): %s@%s',
                         ssh_user, hadoop_host)
    except Exception as e:
        if logger:
            logger.error('拷贝 Hadoop 配置文件异常: %s', e)


def main():
    """CLI 入口：python3 -m utils.prepare_hadoop_conf ..."""
    _script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _script_dir)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )
    logger = logging.getLogger('prepare_hadoop_conf')

    parser = argparse.ArgumentParser(description='预处理 Hadoop 配置文件到部署包目录')
    parser.add_argument('--nodesfile', help='config.yaml 路径（自动从中读取 hadoop 主机和 SSH 配置）')
    parser.add_argument('--hadoop-host', help='Hadoop 主机 IP（与 --nodesfile 二选一；同时提供时优先使用此值）')
    parser.add_argument('--hadoop-user', default='root', help='SSH 用户（默认 root）')
    parser.add_argument('--hadoop-port', type=int, default=22, help='SSH 端口（默认 22）')
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--package-dir', required=True)
    args = parser.parse_args()

    if args.hadoop_host:
        servers_map = {args.hadoop_host: {'username': args.hadoop_user, 'port': args.hadoop_port}}
        comp_hosts = {'hadoop': [args.hadoop_host]}
    elif args.nodesfile:
        from core.parser import load_config  # noqa: F811 - deferred to avoid circular import
        _cfg, servers_map, deploy_map = load_config(args.nodesfile)
        comp_hosts = {}
        for host, comps in deploy_map.items():
            for comp in comps:
                comp_hosts.setdefault(comp, []).append(host)
        logger.info('已加载 %s，Hadoop 主机: %s',
                     args.nodesfile,
                     ', '.join(comp_hosts.get('hadoop', ['无'])))
    else:
        parser.error('请指定 --hadoop-host 或 --nodesfile')

    prepare_hadoop_conf(comp_hosts, servers_map, args.package_dir, args.install_dir, logger)


if __name__ == '__main__':
    main()
