# -*- coding: utf-8 -*-
import json
import os
import sys
import threading

import yaml

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _SCRIPT_DIR)

from core.precheck import precheck_deployment, MANDATORY_ADDRESS_SERVICES
from core.ssh_client import SSHClient, get_ssh_client

# 取消机制：线程安全 Event，用于在同步校验流程中检测用户取消请求
_cancel_event = threading.Event()


def request_cancel():
    _cancel_event.set()


def reset_cancel():
    _cancel_event.clear()


def is_cancelled():
    return _cancel_event.is_set()


def _parse_deploy_structure(cfg):
    servers_map = {}
    for s in cfg.get("servers", []):
        host = s.get("host")
        if host:
            servers_map[host] = s
    deploy_map = {}
    for host, components in cfg.get("deploy", {}).items():
        deploy_map[host] = [c.lower() for c in components]
    comp_hosts = {}
    for host, comps in deploy_map.items():
        for comp in comps:
            comp_hosts.setdefault(comp, []).append(host)
    return comp_hosts, servers_map


class ConfigService(object):
    """配置管理服务：读取、写入、校验 config.yaml"""

    def __init__(self, config_path, web_settings_path):
        self.config_path = config_path
        self.web_settings_path = web_settings_path

    def read_config(self):
        if not os.path.isfile(self.config_path):
            return {}
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, IOError, OSError):
            return {}

    def read_config_raw(self):
        if not os.path.isfile(self.config_path):
            return ""
        with open(self.config_path, "r") as f:
            return f.read()

    def write_config(self, config_dict):
        with open(self.config_path, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)

    def write_config_raw(self, content):
        with open(self.config_path, "w") as f:
            f.write(content)

    def load_web_settings(self):
        defaults = {"install_dir": "", "package_dir": "", "config_dir": "", "http_port": "", "deployed": False, "config_validated": False, "templates_done": False}
        if not os.path.isfile(self.web_settings_path):
            return dict(defaults)
        try:
            with open(self.web_settings_path, "r") as f:
                settings = json.load(f)
            for k, v in defaults.items():
                settings.setdefault(k, v)
            return settings
        except (json.JSONDecodeError, IOError, OSError):
            return dict(defaults)

    def save_web_settings(self, install_dir=None, package_dir=None, config_dir=None, http_port=None, deployed=None, config_validated=None, templates_done=None, last_check=None):
        settings = self.load_web_settings()
        if install_dir is not None:
            settings["install_dir"] = install_dir
        if package_dir is not None:
            settings["package_dir"] = package_dir
        if config_dir is not None:
            settings["config_dir"] = config_dir
        if http_port is not None:
            settings["http_port"] = http_port
        if deployed is not None:
            settings["deployed"] = deployed
        if config_validated is not None:
            settings["config_validated"] = config_validated
        if templates_done is not None:
            settings["templates_done"] = templates_done
        if last_check is not None:
            settings["last_check"] = last_check
        tmp_path = self.web_settings_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(settings, f)
        os.replace(tmp_path, self.web_settings_path)

    def validate_yaml(self, content):
        if not content.strip():
            return ["配置文件内容为空"]
        try:
            yaml.safe_load(content)
            return []
        except yaml.YAMLError as e:
            return ["YAML 解析错误: {}".format(str(e)[:200])]

    def validate_integrity(self, cfg):
        errors = []

        if "deploy" not in cfg or not cfg["deploy"]:
            errors.append("deploy 配置不能为空，请至少指定一个主机和组件")
            return errors

        if "servers" not in cfg or not cfg["servers"]:
            errors.append("servers 配置不能为空，请至少配置一个服务器")
            return errors

        servers_map = {}
        for s in cfg["servers"]:
            host = s.get("host")
            if host:
                servers_map[host] = s

        deploy_map = cfg.get("deploy", {})
        for host in deploy_map:
            if host not in servers_map:
                errors.append("主机 {} 在 deploy 中有配置，但未在 servers 中定义".format(host))

        comp_hosts = {}
        for host, comps in deploy_map.items():
            for comp in comps:
                comp_hosts.setdefault(comp, []).append(host)

        for svc in MANDATORY_ADDRESS_SERVICES:
            hosts = comp_hosts.get(svc, [])
            if not hosts:
                errors.append("核心服务 [{}] 未配置部署地址".format(svc))

        zk_hosts = comp_hosts.get("zookeeper", [])
        if len(zk_hosts) not in (0, 1, 3):
            errors.append("ZooKeeper 主机数量为 {}，必须为 1 或 3".format(len(zk_hosts)))

        nacos_hosts = comp_hosts.get("nacos", [])
        if len(nacos_hosts) not in (0, 1, 3):
            errors.append("Nacos 主机数量为 {}，必须为 1 或 3".format(len(nacos_hosts)))

        kafka_hosts = comp_hosts.get("kafka", [])
        if kafka_hosts and len(kafka_hosts) < 1:
            errors.append("Kafka 主机数量为 {}，必须大于等于 1".format(len(kafka_hosts)))

        hadoop_hosts = comp_hosts.get("hadoop", [])
        if hadoop_hosts and len(hadoop_hosts) < 2:
            errors.append("Hadoop 主机数量为 {}，必须大于等于 2".format(len(hadoop_hosts)))

        mysql_hosts = comp_hosts.get("mysql", [])
        if mysql_hosts and len(mysql_hosts) != 1:
            errors.append("MySQL 主机数量为 {}，必须为 1".format(len(mysql_hosts)))

        redis_hosts = comp_hosts.get("redis", [])
        if redis_hosts and len(redis_hosts) not in (1, 3):
            errors.append("Redis 主机数量为 {}，必须为 1 或 3".format(len(redis_hosts)))

        ckman_hosts = comp_hosts.get("ckman", [])
        if ckman_hosts and len(ckman_hosts) != 1:
            errors.append("ckman 主机数量为 {}，必须为 1".format(len(ckman_hosts)))

        clickhouse_hosts = comp_hosts.get("clickhouse", [])
        if clickhouse_hosts and len(clickhouse_hosts) % 2 != 0:
            errors.append("ClickHouse 主机数量为 {}，必须为偶数".format(len(clickhouse_hosts)))

        return errors

    def validate_ssh(self, cfg):
        errors = []
        results = []

        servers_map = {}
        for s in cfg.get("servers", []):
            host = s.get("host")
            if host:
                servers_map[host] = s

        deploy_map = cfg.get("deploy", {})
        all_hosts = set(deploy_map.keys())

        for host in sorted(all_hosts):
            if is_cancelled():
                errors.append("配置校验已被用户取消")
                results.append({"host": host, "ok": False, "error": "校验已被取消"})
                break
            server_info = servers_map.get(host)
            if not server_info:
                errors.append("主机 {} 未在 servers 配置中找到".format(host))
                results.append({"host": host, "ok": False, "error": "未在 servers 配置中找到"})
                continue
            try:
                ssh = get_ssh_client(server_info, dry_run=False)
                code, _, _ = ssh.execute("echo ok", timeout=15)
                ssh.close()
                if code == 0:
                    results.append({"host": host, "ok": True, "error": ""})
                else:
                    msg = "SSH 免密连接失败（返回码 {}）".format(code)
                    errors.append("主机 {} {}".format(host, msg))
                    results.append({"host": host, "ok": False, "error": msg})
            except Exception as e:
                msg = str(e)[:200]
                errors.append("主机 {} SSH 连接失败: {}".format(host, msg))
                results.append({"host": host, "ok": False, "error": msg})

        return errors, results

    def validate_config(self, content):
        if is_cancelled():
            return ["配置校验已被用户取消"], False, False

        yaml_errors = self.validate_yaml(content)
        if yaml_errors:
            return yaml_errors, False, False

        if is_cancelled():
            return ["配置校验已被用户取消"], False, False

        cfg = yaml.safe_load(content) or {}
        integrity_errors = self.validate_integrity(cfg)
        if integrity_errors:
            return integrity_errors, True, False

        if is_cancelled():
            return ["配置校验已被用户取消"], False, False

        ssh_errors, _ = self.validate_ssh(cfg)
        all_errors = integrity_errors + ssh_errors
        return all_errors, True, True
