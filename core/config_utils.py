# -*- coding: utf-8 -*-
"""配置工具模块 — 统一处理 config.yaml 和模板配置提取"""
import os
import re
import yaml


def get_component_config(config, component):
    """从部署配置中读取指定组件的配置字典

    Args:
        config: DeployConfig namedtuple
        component: 组件名（如 'clickhouse', 'nebula', 'redis'）
    Returns:
        dict: 该组件的配置字典（没有则返回空字典）
    """
    raw = getattr(config, 'raw_config', None) or {}
    return raw.get(component, {}) or {}


def get_port_from_template(template_dir, template_relpath, patterns, default=None):
    """从本地配置模板文件中提取端口号

    Args:
        template_dir: 模板根目录
        template_relpath: 相对于模板根目录的文件路径
        patterns: 正则表达式列表，按顺序匹配
        default: 未找到时的默认值
    Returns:
        int: 提取到的端口号，或 default
    """
    filepath = os.path.join(template_dir, template_relpath)
    if not os.path.isfile(filepath):
        return default
    with open(filepath, 'r') as f:
        content = f.read()
    for pattern in patterns:
        m = re.search(pattern, content)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                continue
    return default


def _template_dir(config):
    return getattr(config, 'config_template_dir', '') or ''


def _get_hosts(context, component):
    return sorted(getattr(context, 'comp_hosts', {}).get(component, []))


def _addr(host, port):
    return '{}:{}'.format(host, port)


def _server_list(hosts, port):
    return ','.join(_addr(h, port) for h in hosts)



def get_port_from_config_or_template(config, component, cfg_key, tpl_path,
                                     tpl_patterns, default):
    """优先从 config.yaml 读取端口，缺失时回退到模板。"""
    cfg = get_component_config(config, component)
    port = cfg.get(cfg_key)
    if port is not None:
        return int(port)
    template_dir = _template_dir(config)
    return get_port_from_template(template_dir, tpl_path, tpl_patterns, default)


# 向后兼容别名
_get_port_from_config_or_template = get_port_from_config_or_template


def get_zookeeper_cluster_hosts(comp_hosts):
    """获取 Zookeeper 集群实际运行的主机列表

    根据 Zookeeper Installer 的部署逻辑：
    - 节点数 > 2：集群模式，前 3 个节点实际运行
    - 节点数 <= 2：单节点模式，仅第 1 个节点运行
    """
    all_hosts = sorted(comp_hosts.get('zookeeper', []))
    if not all_hosts:
        return []
    if len(all_hosts) > 2:
        return all_hosts[:3]
    return all_hosts[:1]


# Nacos

def get_nacos_vars(context, config):
    """获取 Nacos 配置变量（地址、端口、密码等）"""
    hosts = _get_hosts(context, 'nacos')
    if not hosts:
        return None

    cfg = get_component_config(config, 'nacos')
    nacos_port = cfg.get('port', 8848)

    is_cluster = len(hosts) == 3
    nacos_hosts = hosts[:3] if is_cluster else [hosts[0]]
    return {
        'nacos_enabled': 'true',
        'nacos_hosts': nacos_hosts,
        'nacos_servers': _server_list(nacos_hosts, nacos_port),
        'nacos_port': nacos_port,
        'nacos_user': 'nacos',
        'nacos_password': getattr(
            config, 'nacos_password', '0192023A7BBD73250516F069DF18B500'),
        'nacos_is_cluster': is_cluster,
    }


# MySQL

def get_mysql_vars(context, config):
    """获取 MySQL 配置变量（主机、端口、用户、密码）"""
    hosts = _get_hosts(context, 'mysql')
    if not hosts:
        return None

    mysql_cfg = get_component_config(config, 'mysql')
    mysql_port = mysql_cfg.get('port', 3306)

    return {
        'mysql_host': hosts[0],
        'mysql_port': mysql_port,
        'mysql_user': mysql_cfg.get('user', 'root'),
        'mysql_password': getattr(config, 'mysql_password', 'MySQL@123'),
    }


# Redis

def get_redis_vars(context, config):
    """获取 Redis 配置变量（主机、端口、密码、数据库、哨兵配置）"""
    hosts = _get_hosts(context, 'redis')
    if not hosts:
        return None

    cfg = get_component_config(config, 'redis')
    redis_port = cfg.get('port', 6379)
    redis_password = cfg.get('password', 'Redis@123')
    redis_database = cfg.get('database', 0)
    sentinel_port = cfg.get('sentinel_port', 26379)
    sentinel_password = cfg.get('sentinel_password', 'Redis@123')
    sentinel_name = cfg.get('sentinel_name', 'mymaster')

    return {
        'redis_host': hosts[0],
        'redis_port': redis_port,
        'redis_password': redis_password,
        'redis_database': redis_database,
        'sentinel_port': sentinel_port,
        'sentinel_password': sentinel_password,
        'sentinel_name': sentinel_name,
        'redis_servers': _server_list(hosts, redis_port),
        'sentinel_servers': _server_list(hosts, sentinel_port),
    }


# Kafka

def get_kafka_vars(context, config):
    """获取 Kafka 配置变量（主机、端口、服务地址列表）"""
    hosts = _get_hosts(context, 'kafka')
    if not hosts:
        return None

    kafka_cfg = get_component_config(config, 'kafka')
    kafka_port = kafka_cfg.get('port', 9092)

    return {
        'kafka_host': hosts[0],
        'kafka_port': kafka_port,
        'kafka_servers': _server_list(hosts, kafka_port),
    }


# ZooKeeper

def get_zookeeper_vars(context, config):
    """获取 ZooKeeper 配置变量（主机、端口、选举/通信端口、服务地址）"""
    hosts = _get_hosts(context, 'zookeeper')
    if not hosts:
        return None

    zk_cfg = get_component_config(config, 'zookeeper')
    zk_port = zk_cfg.get('port', 2181)
    zk_election_port = zk_cfg.get('election_port', 2888)
    zk_quorum_port = zk_cfg.get('quorum_port', 3888)
    zk_admin_port = zk_cfg.get('admin_port', 8081)

    return {
        'zookeeper_host': hosts[0],
        'zookeeper_port': zk_port,
        'zookeeper_admin_port': zk_admin_port,
        'zookeeper_election_port': zk_election_port,
        'zookeeper_quorum_port': zk_quorum_port,
        'zookeeper_servers': _server_list(hosts, zk_port),
    }


# ckman

def get_ckman_vars(context, config):
    """获取 CKMan 配置变量（主机、端口、密码）"""
    hosts = _get_hosts(context, 'ckman')
    if not hosts:
        return None

    ckman_cfg = get_component_config(config, 'ckman')
    ckman_port = ckman_cfg.get('port', 8808)

    return {
        'ckman_host': hosts[0],
        'ckman_port': ckman_port,
        'ckman_password': 'Ckman123456!',
    }


# ClickHouse

def get_clickhouse_vars(context, config):
    """获取 ClickHouse 配置变量（主机、TCP/HTTP 端口、集群、密码等）"""
    hosts = _get_hosts(context, 'clickhouse')
    if not hosts:
        return None

    cfg = get_component_config(config, 'clickhouse')

    tcp_port = cfg.get('tcp_port', 19000)
    http_port = cfg.get('http_port', 18123)
    host_tcp_ports = _server_list(hosts, tcp_port)
    host_http_ports = _server_list(hosts, http_port)

    return {
        'clickhouse_hosts': hosts,
        'clickhouse_host_tcp_ports': host_tcp_ports,
        'clickhouse_host_http_ports': host_http_ports,
        'clickhouse_tcp_port': tcp_port,
        'clickhouse_http_port': http_port,
        'clickhouse_cluster': cfg.get('cluster', 'ckcluster'),
        'clickhouse_logic_cluster': cfg.get('logic_cluster', 'cklogic'),
        'clickhouse_password': cfg.get('password', 'ck@123'),
        'clickhouse_path': cfg.get('path', '/data/clickhouse/'),
        'clickhouse_ssh_user': cfg.get('ssh_user', 'root'),
        'clickhouse_ssh_port': cfg.get('ssh_port', 22),
        'clickhouse_authenticate_type': cfg.get('authenticate_type', 2),
        'clickhouse_force': cfg.get('force', True),
        'clickhouse_keeper_tcp_port': cfg.get('keeper_tcp_port', 9181),
        'clickhouse_keeper_raft_port': cfg.get('keeper_raft_port', 9234),
    }


# NebulaGraph

def get_nebula_vars(context, config):
    """获取 NebulaGraph 配置变量（主机、meta/storage/graphd 端口、空间配置等）"""
    hosts = _get_hosts(context, 'nebula')
    if not hosts:
        return None

    cfg = get_component_config(config, 'nebula')
    meta_port = cfg.get('meta_port', 9559)

    storaged_port = cfg.get('storaged_port', 9779)

    meta_server_addr = _server_list(hosts, meta_port)
    storaged_server_addr = _server_list(hosts, storaged_port)

    return {
        'nebula_hosts': hosts,
        'nebula_is_cluster': len(hosts) == 3,
        'nebula_meta_port': meta_port,
        'nebula_graphd_port': cfg.get('graphd_port', 9669),
        'nebula_storaged_port': storaged_port,
        'meta_server_addr': meta_server_addr,
        'storaged_server_addr': storaged_server_addr,
        'nebula_graphd_user': cfg.get('graphd_user', 'root'),
        'nebula_graphd_password': cfg.get('graphd_password', 'root'),
        'nebula_space_name': cfg.get('space_name', 'cmdb'),
        'nebula_space_partition_num': cfg.get('space_partition_num', 10),
        'nebula_space_replica_factor': cfg.get('space_replica_factor', 1),
        'nebula_space_vid_type': cfg.get('space_vid_type', 'FIXED_STRING(256)'),
        'nebula_edge_name': cfg.get('edge_name', 'cmdb_object_relation'),
    }


# Nebula Studio

def get_nebula_studio_vars(config):
    """读取 Nebula Studio 配置"""
    cfg = get_component_config(config, 'nebula_studio')
    return {
        'nebula_studio_port': cfg.get('port', 7001),
    }


# MySQL 端口便捷查询

def get_mysql_port(config):
    """便捷函数：直接返回 MySQL 端口（int）"""
    cfg = get_component_config(config, 'mysql')
    return cfg.get('port', 3306)


# 从文件直接加载配置（独立 CLI 工具使用）

def load_config_file(config_path=None):
    """直接从 config.yaml 文件加载基础设施配置，无需 RuntimeContext

    供 CLI 工具（如 odmp_api.py）在没有部署上下文时使用。

    Args:
        config_path: config.yaml 路径，默认在 deploy 目录下查找

    Returns:
        dict: 包含所有组件的主机、端口、密码等信息
              找不到文件或解析失败返回空 dict
    """
    if not config_path:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except (yaml.YAMLError, IOError, OSError):
        return {}

    deploy = raw.get('deploy', {})

    def _first_host(comp):
        for host, comps in deploy.items():
            if comp in comps:
                return host
        return None

    def _all_hosts(comp):
        return [h for h, cs in deploy.items() if comp in cs]

    infra = {}

    nacos_cfg = raw.get('nacos', {})
    nh = _first_host('nacos')
    if nh:
        infra['nacos'] = {
            'addr': _addr(nh, nacos_cfg.get('port', 8848)),
            'password': nacos_cfg.get('password', '0192023A7BBD73250516F069DF18B500'),
        }

    mysql_cfg = raw.get('mysql', {})
    mh = _first_host('mysql')
    if mh:
        infra['mysql'] = {
            'host': mh,
            'port': mysql_cfg.get('port', 3306),
            'password': mysql_cfg.get('password', 'MySQL@123'),
        }

    redis_cfg = raw.get('redis', {})
    rh = _first_host('redis')
    if rh:
        redis_hosts = _all_hosts('redis')
        sentinel_port = redis_cfg.get('sentinel_port', 26379)
        # 与 Redis 安装器 _is_sentinel_mode() 保持一致：3 台主机为哨兵模式
        is_sentinel = len(redis_hosts) == 3
        infra['redis'] = {
            'host': rh,
            'port': redis_cfg.get('port', 6379),
            'password': redis_cfg.get('password', 'Redis@123'),
            'sentinel_servers': _server_list(redis_hosts, sentinel_port) if is_sentinel else '',
            'sentinel_name': redis_cfg.get('sentinel_name', 'mymaster'),
        }

    kafka_cfg = raw.get('kafka', {})
    kh = _all_hosts('kafka')
    if kh:
        kp = kafka_cfg.get('port', 9092)
        infra['kafka'] = {'hosts': kh, 'port': kp}

    nebula_cfg = raw.get('nebula', {})
    nbh = _first_host('nebula')
    if nbh:
        infra['nebula'] = {
            'host': nbh,
            'graphd_port': nebula_cfg.get('graphd_port', 9669),
            'meta_port': nebula_cfg.get('meta_port', 9559),
            'space_name': nebula_cfg.get('space_name', 'cmdb'),
        }

    ckman_cfg = raw.get('ckman', {})
    ckh = _first_host('ckman')
    if ckh:
        ch_cfg = raw.get('clickhouse', {})
        infra['clickhouse'] = {
            'ckman_host': ckh,
            'ckman_port': ckman_cfg.get('port', 8808),
            'host': _first_host('clickhouse') or ckh,
            'http_port': ch_cfg.get('http_port', 18123),
            'tcp_port': ch_cfg.get('tcp_port', 19000),
            'cluster': ch_cfg.get('cluster', 'ckcluster'),
            'password': ch_cfg.get('password', 'ck@123'),
        }

    infra['deploy'] = raw.get('deploy', {})
    infra['zookeeper'] = raw.get('zookeeper', {})
    return infra


# ODMP

def get_odmp_vars(context, config):
    """获取 ODMP 部署所需的依赖服务变量

    从部署上下文中提取 Nacos、MySQL 等 ODMP 依赖的基础设施信息。

    Args:
        context: RuntimeContext（包含 comp_hosts、servers_map 等）
        config: DeployConfig namedtuple

    Returns:
        dict: 包含以下键值
            - nacos_host: str, Nacos 地址 (IP:port)
            - nacos_servers: str, Nacos 集群地址列表 (逗号分隔)
            - nacos_user: str, Nacos 用户名
            - nacos_password: str, Nacos 密码
            - mysql_host: str, MySQL 主机地址
            - mysql_port: str, MySQL 端口
            - mysql_user: str, MySQL 用户名
            - mysql_password: str, MySQL 密码
    """
    nacos_hosts = _get_hosts(context, 'nacos')
    nacos_cfg = get_component_config(config, 'nacos')
    nacos_port = nacos_cfg.get('port', 8848)
    nacos_host = _addr(nacos_hosts[0], nacos_port) if nacos_hosts else '127.0.0.1:8848'
    nacos_servers = _server_list(nacos_hosts, nacos_port) if nacos_hosts else nacos_host

    mysql_hosts = _get_hosts(context, 'mysql')
    mysql_cfg = get_component_config(config, 'mysql')
    mysql_port = mysql_cfg.get('port', 3306)
    mysql_host = mysql_hosts[0] if mysql_hosts else '127.0.0.1'

    return {
        'nacos_host': nacos_host,
        'nacos_servers': nacos_servers,
        'nacos_user': 'nacos',
        'nacos_password': getattr(config, 'nacos_password', '0192023A7BBD73250516F069DF18B500'),
        'mysql_host': mysql_host,
        'mysql_port': str(mysql_port),
        'mysql_user': 'root',
        'mysql_password': getattr(config, 'mysql_password', 'MySQL@123'),
    }


# SSO

def get_sso_vars(context, config):
    """获取 SSO 部署所需的依赖服务变量

    从部署上下文中提取 Nacos、MySQL 等 SSO 依赖的基础设施信息，
    供 SsoInstaller 渲染配置模板和使用。

    Args:
        context: RuntimeContext（包含 comp_hosts、servers_map 等）
        config: DeployConfig namedtuple

    Returns:
        dict: 包含以下键值
            - nacos_host: str, Nacos 地址 (IP:port)
            - nacos_servers: str, Nacos 集群地址列表 (逗号分隔)
            - nacos_user: str, Nacos 用户名
            - nacos_password: str, Nacos 密码
            - mysql_host: str, MySQL 主机地址
            - mysql_port: str, MySQL 端口
            - mysql_user: str, MySQL 用户名
            - mysql_password: str, MySQL 密码
    """
    nacos_hosts = _get_hosts(context, 'nacos')
    nacos_cfg = get_component_config(config, 'nacos')
    nacos_port = nacos_cfg.get('port', 8848)
    nacos_host = _addr(nacos_hosts[0], nacos_port) if nacos_hosts else '127.0.0.1:8848'
    nacos_servers = _server_list(nacos_hosts, nacos_port) if nacos_hosts else nacos_host

    mysql_hosts = _get_hosts(context, 'mysql')
    mysql_cfg = get_component_config(config, 'mysql')
    mysql_port = mysql_cfg.get('port', 3306)
    mysql_host = mysql_hosts[0] if mysql_hosts else '127.0.0.1'

    return {
        'nacos_host': nacos_host,
        'nacos_servers': nacos_servers,
        'nacos_user': 'nacos',
        'nacos_password': getattr(config, 'nacos_password', '0192023A7BBD73250516F069DF18B500'),
        'mysql_host': mysql_host,
        'mysql_port': str(mysql_port),
        'mysql_user': 'root',
        'mysql_password': getattr(config, 'mysql_password', 'MySQL@123'),
    }


# REFINER

def get_refiner_vars(context, config):
    """获取 REFINER 部署所需的依赖服务变量

    从部署上下文中提取 Nacos、MySQL 等 REFINER 依赖的基础设施信息。

    Args:
        context: RuntimeContext（包含 comp_hosts、servers_map 等）
        config: DeployConfig namedtuple

    Returns:
        dict: 包含以下键值
            - nacos_host: str, Nacos 地址 (IP:port)
            - nacos_user: str, Nacos 用户名
            - nacos_password: str, Nacos 密码
            - mysql_host: str, MySQL 主机地址
            - mysql_port: str, MySQL 端口
            - mysql_user: str, MySQL 用户名
            - mysql_password: str, MySQL 密码
    """
    nacos_hosts = _get_hosts(context, 'nacos')
    nacos_cfg = get_component_config(config, 'nacos')
    nacos_port = nacos_cfg.get('port', 8848)
    nacos_host = _addr(nacos_hosts[0], nacos_port) if nacos_hosts else '127.0.0.1:8848'

    mysql_hosts = _get_hosts(context, 'mysql')
    mysql_cfg = get_component_config(config, 'mysql')
    mysql_port = mysql_cfg.get('port', 3306)
    mysql_host = mysql_hosts[0] if mysql_hosts else '127.0.0.1'

    return {
        'nacos_host': nacos_host,
        'nacos_user': 'nacos',
        'nacos_password': getattr(config, 'nacos_password', '0192023A7BBD73250516F069DF18B500'),
        'mysql_host': mysql_host,
        'mysql_port': str(mysql_port),
        'mysql_user': 'root',
        'mysql_password': getattr(config, 'mysql_password', 'MySQL@123'),
    }


# AIMETER

def get_aimeter_vars(context, config):
    """获取 AIMETER 部署所需的依赖服务变量

    从部署上下文中提取 Nacos、MySQL 等 AIMETER 依赖的基础设施信息。

    Args:
        context: RuntimeContext（包含 comp_hosts、servers_map 等）
        config: DeployConfig namedtuple

    Returns:
        dict: 包含以下键值
            - nacos_host: str, Nacos 地址 (IP:port)
            - nacos_user: str, Nacos 用户名
            - nacos_password: str, Nacos 密码
            - mysql_host: str, MySQL 主机地址
            - mysql_port: str, MySQL 端口
            - mysql_user: str, MySQL 用户名
            - mysql_password: str, MySQL 密码
    """
    nacos_hosts = _get_hosts(context, 'nacos')
    nacos_cfg = get_component_config(config, 'nacos')
    nacos_port = nacos_cfg.get('port', 8848)
    nacos_host = _addr(nacos_hosts[0], nacos_port) if nacos_hosts else '127.0.0.1:8848'

    mysql_hosts = _get_hosts(context, 'mysql')
    mysql_cfg = get_component_config(config, 'mysql')
    mysql_port = mysql_cfg.get('port', 3306)
    mysql_host = mysql_hosts[0] if mysql_hosts else '127.0.0.1'

    return {
        'nacos_host': nacos_host,
        'nacos_user': 'nacos',
        'nacos_password': getattr(config, 'nacos_password', '0192023A7BBD73250516F069DF18B500'),
        'mysql_host': mysql_host,
        'mysql_port': str(mysql_port),
        'mysql_user': 'root',
        'mysql_password': getattr(config, 'mysql_password', 'MySQL@123'),
    }


# -- 工厂注册表 --

_VARS_REGISTRY = {
    'nacos': get_nacos_vars,
    'mysql': get_mysql_vars,
    'redis': get_redis_vars,
    'kafka': get_kafka_vars,
    'zookeeper': get_zookeeper_vars,
    'ckman': get_ckman_vars,
    'clickhouse': get_clickhouse_vars,
    'nebula': get_nebula_vars,
    'nebula_studio': get_nebula_studio_vars,
    'odmp': get_odmp_vars,
    'sso': get_sso_vars,
    'refiner': get_refiner_vars,
    'aimeter': get_aimeter_vars,
}


def get_vars(component, context, config):
    """工厂方法：通过组件名获取对应配置变量

    Args:
        component: 组件名（如 'nacos', 'mysql', 'odmp'）
        context: RuntimeContext
        config: DeployConfig

    Returns:
        dict: 该组件的配置变量，未注册的组件返回空 dict
    """
    handler = _VARS_REGISTRY.get(component)
    if handler is None:
        return {}
    result = handler(context, config)
    return result if result is not None else {}
