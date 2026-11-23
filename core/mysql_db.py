# -*- coding: utf-8 -*-
"""MySQL 数据库工具模块 — 供各 installer 复用"""
import os
import shlex
from core.ssh_client import get_ssh_client


def get_mysql_cmd(ssh, install_dir, logger=None):
    """在远程主机上查找 MySQL 客户端二进制文件

    Args:
        ssh: SSHClient 实例，需具备 .execute()、.host、.dry_run 属性
        install_dir: str, 安装根目录
        logger: logging.Logger，可选

    Returns:
        str: mysql 可执行文件路径，未找到则返回 None
    """
    code, out, _ = ssh.execute('which mysql 2>/dev/null')
    if code == 0 and out.strip():
        return out.strip()
    mysql_path = os.path.join(install_dir, 'comms', 'mysql', 'bin', 'mysql')
    code, _, _ = ssh.execute('test -x {}'.format(shlex.quote(mysql_path)))
    if code == 0:
        return mysql_path
    return None


def create_database(ssh, mysql_cmd, mysql_host, mysql_port, db_user, db_password,
                    db_name, logger=None):
    """在远程 MySQL 上创建数据库

    Args:
        ssh: SSHClient 实例
        mysql_cmd: str, mysql 客户端路径
        mysql_host: str, MySQL 主机地址
        mysql_port: str, MySQL 端口
        db_user: str, 数据库用户名
        db_password: str, 数据库密码
        db_name: str, 数据库名
        logger: logging.Logger，可选
    """
    if logger:
        logger.info('[%s] 创建数据库: %s@%s:%s/%s',
                    ssh.host, db_user, mysql_host, mysql_port, db_name)
    code, out, err = ssh.execute(
        r"{} -h {} -P {} -u {} -p{} -e 'CREATE DATABASE IF NOT EXISTS `{}` "
        r"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;' 2>&1"
        .format(mysql_cmd, mysql_host, mysql_port, db_user, shlex.quote(db_password), db_name)
    )
    if code != 0:
        raise RuntimeError('[{}] 创建数据库 {} 失败: {}'.format(ssh.host, db_name, (out or err)[:200]))


def init_schema(ssh, mysql_cmd, mysql_host, mysql_port, db_user, db_password,
                db_name, sql_file, logger=None):
    """在远程 MySQL 上执行 SQL 文件初始化数据库结构

    Args:
        ssh: SSHClient 实例
        mysql_cmd: str, mysql 客户端路径
        mysql_host: str, MySQL 主机地址
        mysql_port: str, MySQL 端口
        db_user: str, 数据库用户名
        db_password: str, 数据库密码
        db_name: str, 数据库名
        sql_file: str, SQL 文件远程路径
        logger: logging.Logger，可选
    """
    if logger:
        logger.info('[%s] 在库 %s 下执行 SQL: %s', ssh.host, db_name, sql_file)
    code, out, err = ssh.execute(
        r"{} -h {} -P {} -u {} -p{} -D {} < {} 2>&1"
        .format(mysql_cmd, mysql_host, mysql_port, db_user, shlex.quote(db_password),
                db_name, shlex.quote(sql_file))
    )
    if code != 0:
        raise RuntimeError('[{}] 初始化数据库 {} 表结构失败: {}'.format(ssh.host, db_name, (out or err)[:200]))


def init_database(ssh, install_dir, mysql_host, mysql_port, db_user, db_password,
                  db_name, sql_file=None, logger=None):
    """查找 mysql 客户端并创建数据库，可选执行初始化 SQL

    供 Nacos/SSO/ODC 等需要创建 MySQL 数据库的组件复用。
    sql_file 为 None 时仅创建数据库（适用于只需建库不需要初始化表的场景）。

    Args:
        ssh: SSHClient 实例
        install_dir: str, 安装根目录
        mysql_host: str, MySQL 主机地址
        mysql_port: str, MySQL 端口
        db_user: str, 数据库用户名
        db_password: str, 数据库密码
        db_name: str, 数据库名
        sql_file: str, SQL 文件远程路径，可选（None 时仅创建数据库）
        logger: logging.Logger，可选

    Raises:
        RuntimeError: 未找到 mysql 客户端时抛出
    """
    mysql_cmd = get_mysql_cmd(ssh, install_dir, logger)
    if not mysql_cmd:
        raise RuntimeError(
            '[{}] 远程主机未找到 mysql 客户端，无法初始化数据库。'
            '请先部署 MySQL 组件（mysql 客户端会自动分发到需要执行数据库命令的主机），'
            '或确保目标主机 {} 上已安装 mysql 命令。'
            .format(ssh.host, mysql_host))

    if sql_file and not ssh.dry_run:
        code, _, _ = ssh.execute('test -f {}'.format(shlex.quote(sql_file)))
        if code != 0:
            if logger:
                logger.warning('[%s] 未找到初始化 SQL 文件: %s', ssh.host, sql_file)
            return

    create_database(ssh, mysql_cmd, mysql_host, mysql_port, db_user, db_password,
                    db_name, logger)

    if sql_file:
        init_schema(ssh, mysql_cmd, mysql_host, mysql_port, db_user, db_password,
                    db_name, sql_file, logger)

    if logger:
        logger.info('[%s] 数据库初始化完成', ssh.host)


def distribute_mysql_client(mysql_installer_cls, current_ssh, config, context, logger,
                            target_hosts, servers_map, comms_dir, package_file):
    """将 MySQL 客户端包分发到目标主机

    Args:
        mysql_installer_cls: MySQLInstaller 类（避免循环导入）
        current_ssh: 当前 SSHClient 实例
        config: 配置对象
        context: 上下文对象
        logger: logging.Logger
        target_hosts: set, 需要 MySQL 客户端的目标主机集合
        servers_map: dict, 主机名 -> 服务器信息映射
        comms_dir: str, 远程 comms 目录路径
        package_file: str, 包文件名
    """
    # 过滤掉已部署 MySQL 的主机（已有完整 mysql 客户端）
    mysql_hosts = set(getattr(context, 'comp_hosts', {}).get('mysql', []))
    hosts_to_check = [h for h in target_hosts if h not in mysql_hosts]
    if not hosts_to_check:
        return

    for host in hosts_to_check:
        server_info = servers_map.get(host)
        if not server_info:
            continue

        remote_ssh = get_ssh_client(server_info, dry_run=current_ssh.dry_run, logger=logger)
        try:
            # 先检查远程主机是否已有 mysql 命令
            existing = get_mysql_cmd(remote_ssh, config.install_dir, logger)
            if existing:
                logger.info('[%s@%s] %s 已存在 mysql 客户端: %s，跳过部署',
                            current_ssh.host, current_ssh.host, host, existing)
                continue

            remote_inst = mysql_installer_cls(remote_ssh, config, context, logger)
            # 直接创建目录，避免调用被覆盖的 _create_dirs（它会在远程创建 mysql 系统用户）
            remote_ssh.execute('mkdir -p {}'.format(shlex.quote(comms_dir)))
            remote_inst.upload_package()
            remote_inst.extract_package()
            remote_inst._cleanup_package()
            logger.info('[%s@%s] MySQL 客户端已部署到 %s', current_ssh.host, current_ssh.host, host)
        finally:
            remote_ssh.close()