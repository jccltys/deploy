import os
import logging
import sys
import yaml

logger = logging.getLogger(__name__)

# 仅 topic 有安全默认值（不涉及敏感地址）
DEFAULT_TOPICS = {
    "alert": {
        "data": "alerts_aiops",
        "rule": "alerts_rule_aiops",
        "unialert": "alerts_aiops_unialert",
    },
    "basic_metrics": {
        "infra": "infra_metrics_aiops",
        "apm": "apm_metrics_aiops",
    },
    "trans_metrics": "bpm_trans_metrics_aiops",
    "trans_details": "bpm_trans_details_aiops",
}

DEFAULT_CONFIG = {
    "mysql": {},
    "kafka": {},
    "topics": DEFAULT_TOPICS,
}


def load_common_config(mockdata_dir=None):
    search_paths = []
    if mockdata_dir:
        search_paths.append(os.path.join(
            mockdata_dir, 'config', 'common_config.yaml'))
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_paths.append(os.path.join(
        script_dir, '..', 'config', 'common_config.yaml'))

    cfg_path_hint = os.path.join(
        os.path.dirname(script_dir), 'config', 'common_config.yaml')

    for path in search_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                logger.info("已加载配置文件: %s", path)

                _check_infra_config(cfg, cfg_path_hint)
                return cfg
            except Exception as e:
                logger.warning("加载配置文件失败 %s: %s", path, e)
                break

    logger.error(
        "=== common_config.yaml 未找到！===\n"
        "请创建配置文件: %s\n"
        "并填写正确的 MySQL 地址/端口/用户/密码 和 Kafka broker 地址。\n"
        "（topic 名称可使用默认值，无需修改）\n"
        "========================================",
        cfg_path_hint)
    return {}


def _check_infra_config(cfg, cfg_path_hint):
    """检查基础设施配置是否缺失，给出提醒。"""
    mysql = cfg.get('mysql')
    if not mysql or not mysql.get('host') or not mysql.get('password'):
        logger.warning(
            "MySQL 配置不完整，请在 %s 中填写正确的地址和密码",
            cfg_path_hint)

    kafka = cfg.get('kafka')
    if not kafka or not kafka.get('brokers'):
        logger.warning(
            "Kafka broker 地址未配置，请在 %s 中填写正确的地址",
            cfg_path_hint)
