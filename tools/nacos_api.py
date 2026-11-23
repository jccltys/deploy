#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nacos 配置中心管理工具 — 发布/查询配置

提供 NacosConfigManager 类供安装器导入使用，也支持 CLI 独立调用。

作为模块导入:
    from tools.nacos_api import NacosConfigManager
    mgr = NacosConfigManager(logger=logger)

    # 通过 SSH（安装器场景）
    token = mgr.login(host, username, password, ssh=ssh_client)
    mgr.publish_config(host, 'app.properties', content, token, ssh=ssh_client)

    # 直接 HTTP（部署机可直连 Nacos）
    token = mgr.login(host, username, password)
    mgr.publish_config(host, 'app.properties', content, token)

CLI 用法:
    # 通过 SSH 发布配置
    python3 deploy/tools/nacos_api.py \
        --nacos-host 192.168.1.2:8848 \
        --ssh-host 192.168.1.100 \
        --data-id authentication.properties \
        --file ./app.properties

    # 直接发布（部署机可直连 Nacos）
    python3 deploy/tools/nacos_api.py \
        --nacos-host 192.168.1.2:8848 \
        --data-id authentication.properties \
        --file ./app.properties \
        --username nacos --password nacos

    # 仅登录获取 token
    python3 deploy/tools/nacos_api.py \
        --nacos-host 192.168.1.2:8848 --action login
"""
import argparse
import base64
import json
import logging
import os
import re
import requests
import shlex
import sys
import time


class NacosConfigManager(object):
    """Nacos 配置中心管理

    支持两种执行模式：
    - SSH 模式：通过远程主机执行 curl 操作 Nacos API（安装器场景）
    - 直连模式：从部署机直接调用 Nacos HTTP API
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _is_user_not_found(err):
        return 'user not found' in str(err).lower()

    def login(self, host, username, password, ssh=None,
              max_retries=5, retry_delay=5):
        """登录 Nacos 获取 accessToken

        Args:
            host: str, Nacos 地址 (IP:Port)
            username: str, Nacos 用户名
            password: str, Nacos 密码
            ssh: SSHClient 实例，提供 execute(cmd) 方法；为 None 时使用直连 HTTP
            max_retries: int, Nacos 未就绪时最大重试次数（默认5）
            retry_delay: int, 重试间隔秒数（默认5）

        Returns:
            str: accessToken
        """
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                if ssh:
                    return self._login_via_ssh(host, username, password, ssh)
                return self._login_direct(host, username, password)
            except RuntimeError as e:
                if self._is_user_not_found(e) and attempt < max_retries:
                    self.logger.warning(
                        '[nacos] Nacos 用户表尚未就绪（第%d次），%d秒后重试...',
                        attempt + 1, retry_delay)
                    time.sleep(retry_delay)
                    last_err = e
                else:
                    raise
        raise last_err

    def _login_via_ssh(self, host, username, password, ssh):
        cmd = (
            "curl -s -X POST 'http://{}/nacos/v1/auth/login' "
            "-d 'username={}' -d 'password={}' 2>&1"
        ).format(host, shlex.quote(username), shlex.quote(password))
        self.logger.info('[nacos] 正在登录 %s', host)
        code, out, err = ssh.execute(cmd)
        if code != 0:
            raise RuntimeError('Nacos 登录失败 (SSH): {}'.format(err.strip()[:200]))
        return self._parse_login_response(out, host)

    def _login_direct(self, host, username, password):
        url = 'http://{}/nacos/v1/auth/login'.format(host)
        self.logger.info('[nacos] 正在登录 %s (直连)', host)
        try:
            r = requests.post(url, data={'username': username, 'password': password},
                              timeout=30)
            r.raise_for_status()
            return self._parse_login_response(r.text, host)
        except requests.RequestException as e:
            raise RuntimeError('Nacos 登录失败 (直连): {}'.format(e))

    @staticmethod
    def _parse_login_response(text, host):
        """解析 Nacos 登录 JSON 响应，提取 accessToken"""
        try:
            result = json.loads(text)
            token = result.get('accessToken')
            if not token:
                raise ValueError('响应中未包含 accessToken')
            return token
        except (json.JSONDecodeError, ValueError) as e:
            # 保留原始响应内容，上层 retry 逻辑依赖 "user not found" 关键字判断
            raise RuntimeError('解析 Nacos 登录响应失败 [{}]: {} — 原始响应: {}'.format(
                host, e, text.strip()[:200]))

    def publish_config(self, host, data_id, content, token, group='DEFAULT_GROUP',
                       config_type=None, ssh=None):
        """发布配置到 Nacos

        Args:
            host: str, Nacos 地址 (IP:Port)
            data_id: str, 配置的 Data ID
            content: str, 配置内容
            token: str, accessToken（由 login() 获取）
            group: str, 配置分组（默认 DEFAULT_GROUP）
            config_type: str or None, 配置格式（可选）
                         支持: TEXT, JSON, XML, YAML, HTML, Properties
                         为 None 时 Nacos 默认为 TEXT
            ssh: SSHClient 实例；为 None 时使用直连 HTTP
        """
        if ssh:
            return self._publish_via_ssh(host, data_id, content, token, group,
                                         config_type, ssh)
        return self._publish_direct(host, data_id, content, token, group,
                                    config_type)

    def _publish_via_ssh(self, host, data_id, content, token, group, config_type,
                         ssh):
        temp_file = '/tmp/nacos_pub_{}.tmp'.format(
            re.sub(r'[^a-zA-Z0-9_]', '_', data_id))
        try:
            encoded = base64.b64encode(content.encode()).decode()
            ssh.execute(
                "echo '{}' | base64 -d > {}".format(encoded, shlex.quote(temp_file)),
                check=True, log_command=False)

            type_part = " -d 'type={}'".format(config_type) if config_type else ''
            cmd = (
                "curl -s -X POST 'http://{}/nacos/v1/cs/configs' "
                "-d 'dataId={}' "
                "-d 'group={}'{} "
                "--data-urlencode 'content@{}' "
                "-d 'accessToken={}' 2>&1"
            ).format(host, data_id, group, type_part, shlex.quote(temp_file), token)
            code, out, err = ssh.execute(cmd)

            if code != 0 or 'true' not in out:
                raise RuntimeError(
                    '上传配置 {} 失败: {}'.format(data_id, (out or err).strip()[:200]))
            self.logger.info('[nacos] 配置 %s 已发布', data_id)
        finally:
            ssh.execute('rm -f {}'.format(shlex.quote(temp_file)))

    def _publish_direct(self, host, data_id, content, token, group, config_type):
        url = 'http://{}/nacos/v1/cs/configs'.format(host)
        self.logger.info('[nacos] 正在发布配置 %s (直连)', data_id)
        try:
            post_data = {
                'dataId': data_id,
                'group': group,
                'content': content,
                'accessToken': token,
            }
            if config_type:
                post_data['type'] = config_type
            r = requests.post(url, data=post_data, timeout=30)
            r.raise_for_status()
            if 'true' not in r.text:
                raise RuntimeError(
                    'Nacos 返回异常: {}'.format(r.text.strip()[:200]))
            self.logger.info('[nacos] 配置 %s 已发布', data_id)
        except requests.RequestException as e:
            raise RuntimeError('发布配置 {} 失败 (直连): {}'.format(data_id, e))

    def query_service_instances(self, host, service_name, token,
                                group='DEFAULT_GROUP', ssh=None):
        """查询 Nacos 上指定服务的已注册实例列表

        Args:
            host: str, Nacos 地址 (IP:Port)
            service_name: str, 服务名称（与 Nacos 注册时一致）
            token: str, accessToken（由 login() 获取）
            group: str, 配置分组（默认 DEFAULT_GROUP）
            ssh: SSHClient 实例；为 None 时使用直连 HTTP

        Returns:
            dict: {
                'service_name': str,
                'total_count': int,
                'healthy_count': int,
                'instances': list[dict],
            }
        """
        if ssh:
            return self._query_instances_via_ssh(
                host, service_name, token, group, ssh)
        return self._query_instances_direct(
            host, service_name, token, group)

    def _query_instances_via_ssh(self, host, service_name, token, group, ssh):
        cmd = (
            "curl -s 'http://{}/nacos/v1/ns/instance/list"
            "?serviceName={}&groupName={}&accessToken={}' 2>&1"
        ).format(host, service_name, group, token)
        self.logger.info('[nacos] 查询服务实例: %s (SSH)', service_name)
        code, out, err = ssh.execute(cmd)
        if code != 0:
            raise RuntimeError(
                '查询 Nacos 服务实例失败 (SSH): {}'.format(err.strip()[:200]))
        return self._parse_instances_response(out, service_name)

    def _query_instances_direct(self, host, service_name, token, group):
        url = 'http://{}/nacos/v1/ns/instance/list'.format(host)
        self.logger.info('[nacos] 查询服务实例: %s (直连)', service_name)
        try:
            r = requests.get(url, params={
                'serviceName': service_name,
                'groupName': group,
                'accessToken': token,
            }, timeout=30)
            r.raise_for_status()
            return self._parse_instances_response(r.text, service_name)
        except requests.RequestException as e:
            raise RuntimeError(
                '查询 Nacos 服务实例失败 (直连): {}'.format(e))

    @staticmethod
    def _parse_instances_response(text, service_name):
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                '解析 Nacos 服务实例响应失败: {}'.format(e))

        hosts = result.get('hosts', [])
        total = len(hosts)
        healthy = sum(1 for h in hosts if h.get('healthy', False))

        return {
            'service_name': service_name,
            'total_count': total,
            'healthy_count': healthy,
            'instances': hosts,
        }

    def change_password(self, host, old_password, new_password, ssh=None):
        """修改 Nacos 管理员密码

        Step 1: POST /nacos/v1/auth/login -> 获取 accessToken
        Step 2: PUT /nacos/v1/auth/users  -> 设置新密码

        Args:
            host: str, Nacos 地址 (IP:Port)
            old_password: str, 当前密码
            new_password: str, 新密码
            ssh: SSHClient 实例；为 None 时使用直连 HTTP

        Raises:
            RuntimeError: 登录或修改失败时抛出
        """
        if old_password == new_password:
            self.logger.info('[nacos] 新旧密码相同，跳过修改')
            return

        if ssh:
            self._change_password_via_ssh(host, old_password, new_password, ssh)
        else:
            self._change_password_direct(host, old_password, new_password)

    def _change_password_via_ssh(self, host, old_password, new_password, ssh):
        self.logger.info('[nacos] 正在登录 %s (SSH)', host)
        login_cmd = (
            "curl -s -X POST 'http://{}/nacos/v1/auth/login' "
            "-d 'username=nacos' -d 'password={}' 2>&1"
        ).format(host, shlex.quote(old_password))
        code, out, err = ssh.execute(login_cmd)
        if code != 0:
            raise RuntimeError('Nacos 登录失败 (SSH): {}'.format(err.strip()[:200]))
        try:
            result = json.loads(out)
            token = result.get('accessToken')
            if not token:
                raise ValueError('响应中未包含 accessToken')
        except (ValueError, json.JSONDecodeError) as e:
            raise RuntimeError('解析 Nacos 登录响应失败 [{}]: {}'.format(host, e))

        self.logger.info('[nacos] 访问令牌获取成功，正在修改密码...')
        change_cmd = (
            "curl -s -X PUT 'http://{}/nacos/v1/auth/users"
            "?username=nacos&newPassword={}' "
            "-H 'Authorization: Bearer {}' 2>&1"
        ).format(host, shlex.quote(new_password), token)
        code, out, err = ssh.execute(change_cmd)
        if code != 0:
            raise RuntimeError('Nacos 密码修改请求失败 (SSH): {}'.format(err.strip()[:200]))
        try:
            body = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError('解析 Nacos 密码修改响应失败 [{}]: {}'.format(host, e))

        if body.get('code') == 200 and body.get('data') == 'update user ok!':
            self.logger.info('[nacos] Nacos 密码修改成功: nacos -> %s', new_password)
        else:
            raise RuntimeError('Nacos 密码修改返回异常 [{}]: {}'.format(host, out.strip()[:200]))

    def _change_password_direct(self, host, old_password, new_password):
        self.logger.info('[nacos] 正在登录 %s (直连)', host)
        login_url = 'http://{}/nacos/v1/auth/login'.format(host)
        try:
            r = requests.post(login_url, data={'username': 'nacos', 'password': old_password},
                              timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError('Nacos 登录请求失败: {}'.format(e))

        try:
            body = r.json()
            token = body.get('accessToken')
            if not token:
                raise ValueError('响应中未包含 accessToken')
        except (ValueError, json.JSONDecodeError) as e:
            raise RuntimeError('解析 Nacos 登录响应失败: {} - 原始响应: {}'.format(
                e, r.text.strip()[:200]))

        self.logger.info('[nacos] 访问令牌获取成功，正在修改密码...')
        change_url = 'http://{}/nacos/v1/auth/users'.format(host)
        try:
            r = requests.put(change_url,
                             params={'username': 'nacos', 'newPassword': new_password},
                             headers={'Authorization': 'Bearer {}'.format(token)},
                             timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError('Nacos 密码修改请求失败: {}'.format(e))

        try:
            body = r.json()
        except json.JSONDecodeError as e:
            raise RuntimeError('解析 Nacos 密码修改响应失败: {} - 原始响应: {}'.format(
                e, r.text.strip()[:200]))

        if body.get('code') == 200 and body.get('data') == 'update user ok!':
            self.logger.info('[nacos] Nacos 密码修改成功: nacos -> %s', new_password)
        else:
            raise RuntimeError('Nacos 密码修改返回异常: {}'.format(r.text.strip()[:200]))

    def check_service_registration(self, host, service_name, token,
                                   group='DEFAULT_GROUP', ssh=None):
        """检查服务是否已在 Nacos 上注册（至少一个健康实例）

        Raises:
            RuntimeError: 无健康实例时抛出
        Returns:
            True
        """
        info = self.query_service_instances(
            host, service_name, token, group, ssh=ssh)
        if info['healthy_count'] == 0:
            raise RuntimeError(
                '服务 {} 未注册到 Nacos 或无健康实例（总计 {}, 健康 {}）'
                .format(service_name, info['total_count'],
                        info['healthy_count']))
        self.logger.info('[nacos] 服务 %s 已注册，健康实例 %d/%d',
                         service_name, info['healthy_count'],
                         info['total_count'])
        return True


def _build_ssh_client(host, port=22, username='root', key_file=None):
    try:
        from core.ssh_client import SSHClient
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from core.ssh_client import SSHClient
    return SSHClient(host, port=port, username=username,
                     key_file=key_file, dry_run=False)


def main():
    parser = argparse.ArgumentParser(
        description='Nacos 配置中心管理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--nacos-host', required=True,
                        help='Nacos 地址 (IP:Port)')
    parser.add_argument('--username', default='nacos',
                        help='Nacos 用户名（默认 nacos）')
    parser.add_argument('--password', default='nacos',
                        help='Nacos 密码（默认 nacos）')
    parser.add_argument('--action', default='publish',
                        choices=['login', 'publish', 'change-password'],
                        help='操作类型（默认 publish）')

    # SSH 连接参数（可选，不指定则使用直连 HTTP）
    parser.add_argument('--ssh-host',
                        help='通过 SSH 主机执行 curl（不指定则直连 Nacos）')
    parser.add_argument('--ssh-port', type=int, default=22,
                        help='SSH 端口（默认 22）')
    parser.add_argument('--ssh-user', default='root',
                        help='SSH 用户名（默认 root）')

    # 发布配置相关
    parser.add_argument('--data-id',
                        help='配置 Data ID')
    parser.add_argument('--group', default='DEFAULT_GROUP',
                        help='配置分组（默认 DEFAULT_GROUP）')
    parser.add_argument('--file',
                        help='配置文件路径（发布时读取此文件内容）')

    # 密码修改相关
    parser.add_argument('--new-password',
                        help='Nacos 新密码（change-password 模式下必填）')
    parser.add_argument('--old-password', default='nacos',
                        help='Nacos 当前密码（默认 nacos）')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('nacos_api')

    mgr = NacosConfigManager(logger=logger)

    # 构建 SSH 客户端（如果指定了 --ssh-host）
    ssh = None
    if args.ssh_host:
        ssh = _build_ssh_client(args.ssh_host, port=args.ssh_port,
                                username=args.ssh_user)

    try:
        if args.action == 'change-password':
            if not args.new_password:
                parser.error('--new-password 是必填参数（change-password 模式下）')
            mgr.change_password(args.nacos_host, args.old_password,
                                args.new_password, ssh=ssh)
            return

        if args.action in ('login', 'publish'):
            token = mgr.login(args.nacos_host, args.username, args.password, ssh=ssh)
            if args.action == 'login':
                print(token)
                return

        if not args.data_id:
            parser.error('--data-id 是必填参数（publish 模式下）')
        if not args.file:
            parser.error('--file 是必填参数（publish 模式下）')
        if not os.path.isfile(args.file):
            parser.error('文件不存在: {}'.format(args.file))

        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read()

        mgr.publish_config(args.nacos_host, args.data_id, content, token,
                           group=args.group, ssh=ssh)
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    sys.exit(main())
