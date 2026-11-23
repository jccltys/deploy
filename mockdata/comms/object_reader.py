# -*- coding: utf-8 -*-
"""
对象实例读取模块 — 从 ODMP 对象实例 xlsx 中读取对象数据

使用 openpyxl 解析 deploy/lib/odmp/10-aiops-objectInstance_*.xlsx，
按类型分组返回 objectId 列表，替代脚本中的 basicInstance.yaml。
"""
import os
import glob
import logging
import openpyxl

logger = logging.getLogger(__name__)

# xlsx 中文 sheet 名 → config/alert_rule_info.csv 中使用的类型名
SHEET_TYPE_MAP = {
    '业务系统': 'Biz_system',
    '模块实例': 'ModInstance',
    'Apache实例': 'Apache',
    'Nginx实例': 'Nginx',
    'WebLogic实例': 'Weblogic',
    'Tomcat实例': 'Tomcat',
    'ZooKeeper实例': 'Zookeeper',
    'Kafka实例': 'Kafka',
    'Redis实例': 'Redis',
    'Oracle实例': 'Oracle',
    'Mysql实例': 'Mysql',
    'Linux': 'Linux',
    '虚拟机': 'VM',
    '宿主机': 'ESXi',
    'PC服务器': 'PCServer',
    '交换机': 'Switch',
    '防火墙': 'Firewall',
    'FC存储交换机': 'FCStorageSwitch',
    'FC存储': 'FCStorage',
}

# 跳过非数据 sheets
SKIP_SHEETS = {'导航', '对象关联', 'hiddenrelationtype', '业务子系统'}


def _find_xlsx():
    """在 lib/odmp/ 下查找对象实例 xlsx 文件"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # comms/ → mockdata/ → deploy/
    deploy_root = os.path.dirname(os.path.dirname(script_dir))
    pattern = os.path.join(deploy_root, 'lib', 'odmp', '10-aiops-objectInstance_*.xlsx')
    files = sorted(glob.glob(pattern))
    return files[0] if files else None


def load_object_ids_by_type(xlsx_path=None):
    """读取 xlsx，返回 {type_name: [object_id, ...]}

    Args:
        xlsx_path: xlsx 文件路径，None 则自动查找
    Returns:
        dict: type_name → objectId 列表（按 vid 列 A 读取）
        文件不存在或解析失败返回空 dict
    """
    if not xlsx_path:
        xlsx_path = _find_xlsx()
    if not xlsx_path or not os.path.isfile(xlsx_path):
        logger.warning('未找到对象实例 xlsx 文件: %s', xlsx_path)
        return {}

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    result = {}

    for sheet_name in wb.sheetnames:
        if sheet_name in SKIP_SHEETS:
            continue
        type_name = SHEET_TYPE_MAP.get(sheet_name)
        if not type_name:
            logger.debug('跳过未映射的 sheet: %s', sheet_name)
            continue

        ws = wb[sheet_name]
        ids = []
        header = None
        obj_id_idx = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                header = list(row) if row else []
                try:
                    obj_id_idx = header.index('对象Id')
                except ValueError:
                    break  # 没有对象Id列，跳过该 sheet
                continue
            if obj_id_idx is None:
                break
            obj_id = row[obj_id_idx] if row and obj_id_idx < len(row) else None
            if obj_id and isinstance(obj_id, str) and obj_id.strip():
                ids.append(obj_id.strip())
        if ids:
            result[type_name] = ids

    wb.close()
    return result


def load_object_detail(xlsx_path=None):
    """读取 xlsx，返回 {object_id: {col_name: value, ...}}

    包含每个对象的所有列数据，供需要完整字段的脚本使用。
    """
    if not xlsx_path:
        xlsx_path = _find_xlsx()
    if not xlsx_path or not os.path.isfile(xlsx_path):
        return {}

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    result = {}

    for sheet_name in wb.sheetnames:
        if sheet_name in SKIP_SHEETS:
            continue
        ws = wb[sheet_name]
        headers = None
        obj_id_idx = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = list(row) if row else []
                try:
                    obj_id_idx = headers.index('对象Id')
                except ValueError:
                    break
                continue
            if obj_id_idx is None:
                break
            if not row or obj_id_idx >= len(row):
                continue
            obj_id = str(row[obj_id_idx]).strip() if row[obj_id_idx] else ''
            if not obj_id:
                continue
            detail = {}
            for j, h in enumerate(headers):
                if h and j < len(row):
                    detail[str(h)] = row[j]
            detail['_sheet'] = sheet_name
            result[obj_id] = detail

    wb.close()
    return result


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ids_by_type = load_object_ids_by_type()
    for t, ids in sorted(ids_by_type.items()):
        print(f'{t}: {len(ids)} objects -> {ids[:3]}...')
