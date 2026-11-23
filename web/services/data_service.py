# -*- coding: utf-8 -*-
"""从 config.yaml 加载真实部署数据，供各模板使用。"""

from web.services.config_service import ConfigService

# 组件分类与部署顺序（与 AGENTS.md 一致）
CORE_ORDER = ['java', 'mysql', 'redis', 'zookeeper', 'kafka', 'hadoop', 'nacos', 'ckman', 'clickhouse', 'nebula', 'nebula_studio']
CUSTOM_ORDER = ['sso', 'odmp', 'dolphinscheduler', 'jax-pyenv', 'datax', 'refiner', 'aimeter', 'odc']
# 自动安装到所有主机的组件（无需在 deploy 中列出）
ALWAYS_INSTALLED = ['java', 'java11', 'java21']


def get_comp_group(name):
    name = name.lower()
    if name in (c.lower() for c in CORE_ORDER):
        return 'core'
    if name in (c.lower() for c in CUSTOM_ORDER):
        return 'custom'
    return 'common'


def _deduce_all_hosts(comp_hosts):
    """从 comp_hosts 中推断全量主机列表（取 components 分布最多的主机集合）。"""
    if not comp_hosts:
        return []
    # 取安装组件最多的主机的集合作为"所有主机"
    comps_per_host = {}
    for comp, hosts in comp_hosts.items():
        for h in hosts:
            comps_per_host.setdefault(h, set()).add(comp)
    return sorted(comps_per_host.keys(), key=lambda h: len(comps_per_host[h]), reverse=True)


def load_deployment_data(config_path, web_settings_path):
    """加载配置并返回结构化部署数据。"""
    svc = ConfigService(config_path, web_settings_path) if config_path else None
    if not svc:
        return {'components': [], 'hosts': [], 'services': [], 'stats': {}}

    cfg = svc.read_config()
    if not cfg:
        return {'components': [], 'hosts': [], 'services': [], 'stats': {}}

    deploy_map = cfg.get('deploy', {})

    # 构建 component → hosts 映射
    comp_hosts = {}
    for host, comps in deploy_map.items():
        for comp in comps:
            comp_lower = comp.lower()
            comp_hosts.setdefault(comp_lower, []).append(host)

    all_hosts = _deduce_all_hosts(comp_hosts)

    # 自动安装的组件补充到所有主机
    for name in ALWAYS_INSTALLED:
        if name not in comp_hosts and all_hosts:
            comp_hosts[name] = list(all_hosts)

    # 按分类 + 顺序构造有序组件列表
    seen = set()
    components = []

    for name in CORE_ORDER:
        if name in comp_hosts:
            components.append({'name': name, 'group': 'core', 'hosts': comp_hosts[name]})
            seen.add(name)

    for name in sorted(comp_hosts.keys()):
        if name not in seen and get_comp_group(name) == 'common':
            components.append({'name': name, 'group': 'common', 'hosts': comp_hosts[name]})
            seen.add(name)

    for name in CUSTOM_ORDER:
        if name in comp_hosts and name not in seen:
            components.append({'name': name, 'group': 'custom', 'hosts': comp_hosts[name]})
            seen.add(name)

    # 任何遗漏的组件
    for name in comp_hosts:
        if name not in seen:
            components.append({'name': name, 'group': get_comp_group(name), 'hosts': comp_hosts[name]})

    # 构建主机列表
    servers_map = {}
    for s in cfg.get('servers', []):
        host = s.get('host')
        if host:
            servers_map[host] = s

    hosts = []
    for host, comps in deploy_map.items():
        hosts.append({
            'ip': host,
            'components': [c.lower() for c in comps],
        })

    # 组件安装顺序 pipeline（供 deploy 页面使用）
    order_pipeline = [(c['name'], c['group']) for c in components]

    # 服务列表（供 deploy 页面 select 使用）
    services = sorted(set(c['name'] for c in components))

    stats = {
        'component_count': len(components),
        'host_count': len(hosts),
    }

    return {
        'components': components,
        'hosts': hosts,
        'order_pipeline': order_pipeline,
        'services': services,
        'stats': stats,
    }
