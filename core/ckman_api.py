# -*- coding: utf-8 -*-
"""ckman HTTP API 工具模块 — 供 installer 复用"""
import json
import hashlib
import time

import requests


def _api_url(host, port, path):
    return 'http://{}:{}{}'.format(host, port, path)


def ckman_login(host, port, username, password, logger=None):
    """调用 ckman /api/login 获取 access token

    Returns:
        str: token 字符串
    Raises:
        RuntimeError: 登录失败
    """
    password_md5 = hashlib.md5(password.encode()).hexdigest()
    url = _api_url(host, port, '/api/login')
    payload = {'username': username, 'password': password_md5}
    if logger:
        logger.info('[ckman] POST %s', url)
    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        raise RuntimeError('ckman 登录请求失败: {}'.format(e))
    if resp.status_code != 200:
        raise RuntimeError('ckman 登录失败 (HTTP {}): {}'.format(
            resp.status_code, resp.text.strip()[:200]))
    data = resp.json()
    if data.get('retCode') != '0000':
        raise RuntimeError('ckman 登录返回错误: {} {}'.format(
            data.get('retCode'), data.get('retMsg')))
    token = data.get('entity', {}).get('token')
    if not token:
        raise RuntimeError('ckman 登录响应缺少 token')
    if logger:
        logger.info('[ckman] 登录成功，获取 token')
    return token


def ckman_upload_package(host, port, token, package_path, logger=None):
    """调用 ckman /api/v1/package 上传单个 RPM 安装包

    Args:
        package_path: str, 本地 RPM 文件绝对路径
    Returns:
        dict: ckman 返回的 JSON 数据
    Raises:
        RuntimeError: 上传失败
    """
    url = _api_url(host, port, '/api/v1/package')
    headers = {'token': token}
    pkg_name = package_path.split('/')[-1]
    if logger:
        logger.info('[ckman] POST %s, 文件: %s', url, pkg_name)
    with open(package_path, 'rb') as f:
        files = {'package': (pkg_name, f)}
        try:
            resp = requests.post(url, headers=headers, files=files, timeout=120)
        except requests.exceptions.RequestException as e:
            raise RuntimeError('ckman 上传包请求失败: {}'.format(e))
    if resp.status_code != 200:
        raise RuntimeError('ckman 上传包失败 (HTTP {}): {}'.format(
            resp.status_code, resp.text.strip()[:200]))
    data = resp.json()
    if logger:
        logger.info('[ckman] 上传 %s 返回: %s', pkg_name, data)
    if data.get('retCode') != '0000':
        raise RuntimeError('ckman 上传包返回错误: {} {}'.format(
            data.get('retCode'), data.get('retMsg')))
    return data


def ckman_deploy_clickhouse(host, port, token, deploy_config, logger=None):
    """调用 ckman /api/v1/deploy/ck 部署 ClickHouse 集群

    Args:
        deploy_config: dict, 部署配置 JSON（含 clickhouse, hosts, password 等）
    Raises:
        RuntimeError: 部署请求失败
    """
    url = _api_url(host, port, '/api/v1/deploy/ck')
    headers = {'token': token, 'Content-Type': 'application/json'}
    if logger:
        logger.info('[ckman] POST %s, cluster=%s',
                    url, deploy_config.get('clickhouse', {}).get('clusterName'))
    try:
        resp = requests.post(url, headers=headers,
                             data=json.dumps(deploy_config), timeout=120)
    except requests.exceptions.RequestException as e:
        raise RuntimeError('ckman 部署请求失败: {}'.format(e))
    if resp.status_code != 200:
        raise RuntimeError('ckman 部署失败 (HTTP {}): {}'.format(
            resp.status_code, resp.text.strip()[:200]))
    data = resp.json()
    if data.get('retCode') != '0000':
        raise RuntimeError('ckman 部署返回错误: {} {}'.format(
            data.get('retCode'), data.get('retMsg')))
    if logger:
        logger.info('[ckman] ClickHouse 部署任务已提交')
    return data


def ckman_get_cluster(host, port, token, cluster_name, logger=None):
    """调用 ckman /api/v1/ck/get/{clusterName} 查询 ClickHouse 集群详情

    Args:
        cluster_name: str, 集群名称
    Returns:
        dict: 集群详情（含 status、nodes 等）
    Raises:
        RuntimeError: 查询失败或集群不存在
    """
    url = _api_url(host, port, '/api/v1/ck/get/{}'.format(cluster_name))
    headers = {'token': token}
    if logger:
        logger.info('[ckman] GET %s', url)
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        raise RuntimeError('ckman 查询集群请求失败: {}'.format(e))
    if resp.status_code != 200:
        raise RuntimeError('ckman 查询集群失败 (HTTP {}): {}'.format(
            resp.status_code, resp.text.strip()[:200]))
    data = resp.json()
    if data.get('retCode') != '0000':
        raise RuntimeError('ckman 查询集群返回错误: {} {}'.format(
            data.get('retCode'), data.get('retMsg')))
    cluster_info = data.get('entity', {})
    if not cluster_info:
        raise RuntimeError('ckman 集群 {} 不存在或返回为空'.format(cluster_name))
    if logger:
        logger.info('[ckman] 集群 %s 状态: %s', cluster_name,
                    cluster_info.get('status', 'unknown'))
    return cluster_info


def ckman_wait_for_deploy(host, port, token, cluster_name, logger=None,
                          max_wait=300, interval=5):
    """轮询等待 ClickHouse 部署完成

    Args:
        cluster_name: str, 部署的集群名称
        max_wait: int, 最大等待秒数（默认 300）
        interval: int, 轮询间隔秒数（默认 5）
    Raises:
        RuntimeError: 部署超时或查询失败
    """
    if logger:
        logger.info('[ckman] 等待 ClickHouse 集群 %s 部署完成，超时 %d 秒',
                    cluster_name, max_wait)

    url = _api_url(host, port, '/api/v1/cluster')
    headers = {'token': token}
    waited = 0

    while waited < max_wait:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            if logger:
                logger.warning('[ckman] 查询集群状态失败: %s', e)
            time.sleep(interval)
            waited += interval
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if data.get('retCode') == '0000':
                clusters = data.get('entity', {}).get('clusters', {})
                if cluster_name in clusters:
                    cluster_info = clusters[cluster_name]
                    status = cluster_info.get('status', 'unknown')
                    if status in ('green', 'running', 'ready'):
                        if logger:
                            logger.info('[ckman] ClickHouse 集群 %s 部署成功，状态: %s',
                                        cluster_name, status)
                        return cluster_info
                    else:
                        if logger:
                            logger.info('[ckman] ClickHouse 集群 %s 状态: %s，继续等待...',
                                        cluster_name, status)
                else:
                    if logger:
                        logger.info('[ckman] ClickHouse 集群 %s 尚未就绪，继续等待...',
                                    cluster_name)
            else:
                if logger:
                    logger.warning('[ckman] 查询集群返回错误: %s %s',
                                     data.get('retCode'), data.get('retMsg'))
        else:
            if logger:
                logger.warning('[ckman] 查询集群 HTTP %d: %s',
                               resp.status_code, resp.text.strip()[:200])

        time.sleep(interval)
        waited += interval

    raise RuntimeError('ckman ClickHouse 集群 {} 部署等待超时（{} 秒）'.format(cluster_name, max_wait))
