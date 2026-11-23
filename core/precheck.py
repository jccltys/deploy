# -*- coding: utf-8 -*-
"""部署前预检查模块 — 供 install.py 和外部工具复用"""
import sys


# 必须配置部署地址的核心服务（即使不部署也要配置地址，只是不需要放置安装包）
MANDATORY_ADDRESS_SERVICES = [
    'mysql', 'redis', 'zookeeper', 'kafka', 'clickhouse', 'hadoop', 'nacos', 'ckman',
]


def precheck_deployment(comp_hosts, servers_map, config, context, logger, get_ssh_client):
    """部署前预检查：SSH 免密验证、sudo 能力探测、组件主机数量校验、核心服务地址检查

    Args:
        comp_hosts: dict, 组件名 -> 主机列表
        servers_map: dict, 主机名 -> SSH 配置
        config: DeployConfig namedtuple
        context: RuntimeContext（探测结果写入 context.sudo_mode）
        logger: logging.Logger
        get_ssh_client: callable, 创建 SSHClient 的函数
    """
    errors = []

    # 核心服务地址检查：mysql、redis、zookeeper、kafka、clickhouse、hadoop、nacos、ckman
    # 必须在 deploy 中配置主机地址（即使不需要部署，也要配置地址，只是不放置安装包）
    for svc in MANDATORY_ADDRESS_SERVICES:
        hosts = comp_hosts.get(svc, [])
        if not hosts:
            errors.append(
                '核心服务 [{}] 未配置部署地址，请在 config.yaml 的 deploy 中为该服务配置主机地址。'
                '即使该服务已经部署好不需要再次安装，也必须配置地址。'.format(svc)
            )

    # SSH 免密检查（debug 模式跳过）
    if not config.debug:
        logger.info('--- 预检查：SSH 免密连接验证 ---')
        all_hosts = set()
        for hosts in comp_hosts.values():
            all_hosts.update(hosts)
        for host in sorted(all_hosts):
            server_info = servers_map.get(host)
            if not server_info:
                errors.append('主机 {} 未在 servers 配置中找到'.format(host))
                continue
            try:
                ssh = get_ssh_client(server_info, dry_run=False, logger=logger)
                code, _, _ = ssh.execute('echo ok')
                if code != 0:
                    errors.append('主机 {} SSH 免密连接失败（返回码 {}）'.format(host, code))
                else:
                    logger.info('主机 %s SSH 免密连接正常', host)
                    # 探测 sudo 能力（一次性，供后续组件判断是否走 systemd）
                    username = server_info.get('username', 'root')
                    if username == 'root':
                        mode = 'root'
                    else:
                        sudo_code, _, _ = ssh.execute('sudo -n true')
                        mode = 'sudo' if sudo_code == 0 else 'none'
                    context.sudo_mode[ssh.host] = mode
                    logger.info('主机 %s sudo 能力: %s', host, mode)
                ssh.close()
            except Exception as e:
                errors.append('主机 {} SSH 连接失败: {}'.format(host, str(e)[:200]))
    else:
        logger.info('调试模式：跳过 SSH 免密连接验证')

    # ZooKeeper 数量检查（必须为 1 或 3，0 不报错）
    zk_hosts = comp_hosts.get('zookeeper', [])
    if len(zk_hosts) not in (0, 1, 3):
        errors.append('ZooKeeper 主机数量为 {}，必须为 1 或 3'.format(len(zk_hosts)))

    # Nacos 数量检查（必须为 1 或 3，0 不报错）
    nacos_hosts = comp_hosts.get('nacos', [])
    if len(nacos_hosts) not in (0, 1, 3):
        errors.append('Nacos 主机数量为 {}，必须为 1 或 3'.format(len(nacos_hosts)))

    # Kafka 数量检查（>=1，0 不报错）
    kafka_hosts = comp_hosts.get('kafka', [])
    if kafka_hosts and len(kafka_hosts) < 1:
        errors.append('Kafka 主机数量为 {}，必须大于等于 1'.format(len(kafka_hosts)))

    # Hadoop 数量检查（>=2，0 不报错）
    hadoop_hosts = comp_hosts.get('hadoop', [])
    if hadoop_hosts and len(hadoop_hosts) < 2:
        errors.append('Hadoop 主机数量为 {}，必须大于等于 2'.format(len(hadoop_hosts)))

    # MySQL 主机数量检查（必须为 1，0 不报错）
    mysql_hosts = comp_hosts.get('mysql', [])
    if mysql_hosts and len(mysql_hosts) != 1:
        errors.append('MySQL 主机数量为 {}，必须为 1'.format(len(mysql_hosts)))

    # Redis 主机数量检查（必须为 1 或 3，0 表示不部署 Redis）
    redis_hosts = comp_hosts.get('redis', [])
    if redis_hosts and len(redis_hosts) not in (1, 3):
        errors.append('Redis 主机数量为 {}，必须为 1 或 3'.format(len(redis_hosts)))

    # ckman 主机数量检查（必须为 1，0 表示不部署 ckman）
    ckman_hosts = comp_hosts.get('ckman', [])
    if ckman_hosts and len(ckman_hosts) != 1:
        errors.append('ckman 主机数量为 {}，必须为 1'.format(len(ckman_hosts)))

    # ClickHouse 主机数量检查（必须为偶数，0 表示不部署 ClickHouse）
    clickhouse_hosts = comp_hosts.get('clickhouse', [])
    if clickhouse_hosts and len(clickhouse_hosts) % 2 != 0:
        errors.append('ClickHouse 主机数量为 {}，必须为偶数（2、4、6...）'.format(len(clickhouse_hosts)))

    # Nebula Graph 主机数量检查（必须为 1 或 3，0 表示不部署）
    nebula_hosts = comp_hosts.get('nebula', [])
    if nebula_hosts and len(nebula_hosts) not in (1, 3):
        errors.append('Nebula Graph 主机数量为 {}，必须为 1 或 3'.format(len(nebula_hosts)))

    # Nebula Studio 主机数量检查（必须为 1，0 表示不部署）
    nebula_studio_hosts = comp_hosts.get('nebula_studio', [])
    if nebula_studio_hosts and len(nebula_studio_hosts) != 1:
        errors.append('Nebula Studio 主机数量为 {}，必须为 1'.format(len(nebula_studio_hosts)))

    if errors:
        logger.error('===== 预检查失败 =====')
        for err in errors:
            logger.error('  - %s', err)
        logger.error('请修复以上问题后重新运行部署。')
        sys.exit(1)
    else:
        logger.info('--- 预检查通过 ---')
