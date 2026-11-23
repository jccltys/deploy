# -*- coding: utf-8 -*-
"""
配置解析模块 — 加载 YAML 配置文件并解析服务器和部署映射
"""
import yaml


def load_config(config_path):
    """加载 YAML 配置文件，返回 (完整配置, 服务器映射, 部署映射)"""
    with open(config_path, 'r') as f:
        cfg = yaml.safe_load(f)

    # 解析部署映射：主机 → 组件列表
    deploy_map = {}
    for host, components in cfg.get('deploy', {}).items():
        deploy_map[host] = [c.lower() for c in components]

    # 解析服务器列表：主机 → SSH 连接信息
    servers_map = {}
    for s in cfg.get('servers', []):
        servers_map[s['host']] = s

    return cfg, servers_map, deploy_map
