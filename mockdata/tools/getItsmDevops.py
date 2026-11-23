#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITSM & DevOps 数据模拟及数据库导入工具 (refactored)
"""
import os
import sys
import random
import time
import argparse
import pymysql
from datetime import datetime

from comms.object_reader import load_object_detail
from comms.logger import generator_logger as logger
from comms.config_loader import load_common_config


def get_mysql_config(cfg):
    """从配置字典中提取 MySQL 连接参数，缺失时给出提醒。"""
    mysql = cfg.get('mysql', {}) if cfg else {}
    if not mysql.get('host') or not mysql.get('password'):
        logger.error(
            "MySQL 配置不完整，请在 common_config.yaml 中配置 mysql.host、mysql.port、"
            "mysql.user、mysql.password")
        return None
    return {
        k: mysql.get(k)
        for k in ('host', 'port', 'user', 'password')
    }

names = ["张三", "李四", "王五", "赵六", "孙七", "周八"]
areas = ["华东", "华南", "华北", "西南", "东北"]
ticket_requester_names = ["张三", "李四", "王五", "赵六", "孙七", "周八", "吴九"]
change_manager_names = ["经理-张三", "经理-李四", "经理-王五", "经理-赵六", "经理-孙七", "经理-周八"]
date_format = "%Y-%m-%d %H:%M:%S"

BIZ_SHEET = "业务系统"


def load_system_names(xlsx_path=None):
    details = load_object_detail(xlsx_path)
    systems = []
    for obj_id, detail in details.items():
        if detail.get("_sheet") == BIZ_SHEET:
            name = detail.get("对象名称")
            if name and isinstance(name, str) and name.strip():
                systems.append(name.strip())
    return systems


def generate_devops_data(base_time, selected_systems):
    records = []
    base_time_str = base_time.strftime(date_format)
    for system_name in selected_systems:
        record = (
            f"DEV-{random.randint(1000000, 9999999)}",
            f"WID-{random.randint(10000, 99999)}-{random.randint(100, 999)}",
            random.choice(names),
            system_name,
            f"SYS-{random.randint(100, 999)}",
            base_time_str,
            f"计划-{random.randint(1, 50)}",
            f"NEED-{random.randint(1000, 9999)}",
            random.choice(names),
            f"EXEC-{random.randint(1000, 9999)}",
            random.choice(names),
            f"MAN-{random.randint(1000, 9999)}",
            random.choice(areas),
            "这是一个投产描述信息。",
            base_time_str,
        )
        records.append(record)
    return records


def generate_itsm_data(base_time, selected_systems):
    records = []
    base_time_str = base_time.strftime(date_format)
    for system_name in selected_systems:
        record = (
            f"变更总结-{random.randint(1, 1000)}",
            f"TICKET-{random.randint(10000, 99999)}-{random.randint(100, 999)}",
            base_time_str,
            base_time_str,
            system_name,
            f"服务项-{random.randint(1, 20)}",
            random.choice(["Low", "Medium", "High"]),
            f"变更类型-{random.randint(1, 5)}",
            random.choice(["Open", "In Progress", "Closed"]),
            base_time_str,
            random.choice(ticket_requester_names),
            random.choice(change_manager_names),
            "这是一个 ITSM 变更描述。",
            random.choice(["Development", "Testing", "Production"]),
            base_time_str,
            base_time_str,
        )
        records.append(record)
    return records


def setup_db_and_tables(mysql_cfg):
    try:
        conn = pymysql.connect(
            host=mysql_cfg["host"],
            port=mysql_cfg["port"],
            user=mysql_cfg["user"],
            password=mysql_cfg["password"],
            charset="utf8mb4",
        )
        cursor = conn.cursor()
        cursor.execute(
            "CREATE DATABASE IF NOT EXISTS itsm "
            "DEFAULT CHARACTER SET 'utf8mb4'"
        )
        cursor.execute("USE itsm")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS itsm_devops (
              id VARCHAR(50) NOT NULL COMMENT '记录唯一ID',
              workid VARCHAR(50) NOT NULL COMMENT '工单编号',
              name VARCHAR(50) NOT NULL COMMENT '姓名',
              system VARCHAR(100) NOT NULL COMMENT '所属系统',
              systemid VARCHAR(50) NOT NULL COMMENT '系统ID',
              plandate DATETIME NOT NULL COMMENT '计划日期',
              plan VARCHAR(200) NOT NULL COMMENT '计划内容',
              needid VARCHAR(50) NOT NULL COMMENT '需求ID',
              executor VARCHAR(50) NOT NULL COMMENT '执行人',
              executorid VARCHAR(50) NOT NULL COMMENT '执行人ID',
              manager VARCHAR(50) NOT NULL COMMENT '负责人',
              managerid VARCHAR(50) NOT NULL COMMENT '负责人ID',
              area VARCHAR(50) NOT NULL COMMENT '区域',
              `describe` VARCHAR(500) NOT NULL COMMENT '描述信息',
              `date` DATETIME NOT NULL COMMENT '生成日期',
              PRIMARY KEY (id),
              KEY idx_workid (workid),
              KEY idx_system (system),
              KEY idx_date (`date`)
            ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_general_ci;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS itsm_tickets (
              id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
              ticket_summary VARCHAR(255) NOT NULL COMMENT '变更总结',
              ticket_no VARCHAR(50) NOT NULL UNIQUE COMMENT '工单号',
              actual_starttime DATETIME DEFAULT NULL COMMENT '实际开始时间',
              actual_endtime DATETIME DEFAULT NULL COMMENT '实际结束时间',
              application_system VARCHAR(100) DEFAULT NULL COMMENT '所属业务系统',
              service_item_name VARCHAR(100) DEFAULT NULL COMMENT '服务项名称',
              change_risk_level VARCHAR(20) DEFAULT NULL COMMENT '变更风险等级',
              change_type_desc VARCHAR(100) DEFAULT NULL COMMENT '变更类型描述',
              ticket_status VARCHAR(50) DEFAULT NULL COMMENT '工单状态',
              ticket_createtime DATETIME DEFAULT NULL COMMENT '工单创建时间',
              ticket_requester_name VARCHAR(100) DEFAULT NULL COMMENT '请求人',
              change_manager_name VARCHAR(100) DEFAULT NULL COMMENT '变更管理员',
              ticket_desc TEXT COMMENT '工单描述',
              change_environment VARCHAR(50) DEFAULT NULL COMMENT '变更环境',
              nowdate DATETIME DEFAULT NULL COMMENT '批次时间',
              date DATETIME DEFAULT NULL COMMENT '工单时间',
              INDEX idx_ticket_status (ticket_status),
              INDEX idx_application_system (application_system),
              INDEX idx_ticket_createtime (ticket_createtime)
            ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'ITSM 工单表';
        """)

        conn.commit()
        return conn, cursor
    except pymysql.MySQLError as e:
        logger.error("数据库初始化失败: %s", e)
        sys.exit(1)


def find_xlsx(deploy_dir):
    xlsx_dir = os.path.join(deploy_dir, 'lib', 'odmp')
    if not os.path.isdir(xlsx_dir):
        return None
    for fname in os.listdir(xlsx_dir):
        if fname.startswith("10-aiops-objectInstance") and fname.endswith(".xlsx"):
            return os.path.join(xlsx_dir, fname)
    return None


def _generate_batch(base_time, system_names, mysql_cfg, debug, logger):
    """生成一批 ITSM 和 DevOps 数据并写入 MySQL。"""
    selected_systems = random.sample(system_names, min(len(system_names), 2))
    logger.info("随机选择的系统: %s", selected_systems)

    devops_data = generate_devops_data(base_time, selected_systems)
    itsm_data = generate_itsm_data(base_time, selected_systems)
    data_count = len(selected_systems)

    if debug:
        logger.info("--- [DEBUG] 模拟生成 %d 条数据 ---", data_count)
        for d in devops_data:
            logger.info("DevOps 数据: %s", d)
        for d in itsm_data:
            logger.info("ITSM 数据: %s", d)
        return True

    conn, cursor = setup_db_and_tables(mysql_cfg)
    try:
        sql_devops = (
            "INSERT INTO itsm_devops "
            "(id, workid, name, system, systemid, plandate, plan, needid, "
            "executor, executorid, manager, managerid, area, `describe`, date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.executemany(sql_devops, devops_data)

        sql_itsm = (
            "INSERT INTO itsm_tickets "
            "(ticket_summary, ticket_no, actual_starttime, actual_endtime, "
            "application_system, service_item_name, change_risk_level, "
            "change_type_desc, ticket_status, ticket_createtime, "
            "ticket_requester_name, change_manager_name, ticket_desc, "
            "change_environment, nowdate, date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.executemany(sql_itsm, itsm_data)

        conn.commit()
        logger.info("成功导入 %d 条 DevOps 数据和 %d 条 ITSM 数据", data_count, data_count)
    except pymysql.MySQLError as e:
        logger.error("数据导入失败: %s", e)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

    return True


def run(system_names, start=None, end=None, debug=False, mockdata_dir=None):
    try:
        if not system_names:
            logger.error("未加载到业务系统名称")
            return False

        logger.info("已加载 %d 个业务系统名称", len(system_names))

        cfg = load_common_config(mockdata_dir)
        mysql_cfg = get_mysql_config(cfg)
        if not mysql_cfg:
            logger.error("MySQL 配置不完整，跳过 ITSM/DevOps 数据生成。")
            return False
        logger.info("MySQL 地址: %s:%d", mysql_cfg["host"], mysql_cfg["port"])

        if start and end:
            base_time = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            return _generate_batch(base_time, system_names, mysql_cfg, debug, logger)

        while True:
            base_time = datetime.now()
            ok = _generate_batch(base_time, system_names, mysql_cfg, debug, logger)
            if not ok:
                return False
            if debug:
                break
            logger.info("24小时后生成下一批 ITSM/DevOps 数据...")
            time.sleep(24 * 60 * 60)

        return True
    except Exception as e:
        logger.error("ITSM & DevOps 数据生成失败: %s", e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ITSM & DevOps 数据模拟及数据库导入工具")
    parser.add_argument("--debug", action="store_true", help="调试模式，仅打印不写入数据库")
    parser.add_argument("--start", type=str, help="指定数据生成的日期点 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, default=None,
                        help="结束时间（兼容统一启动器透传，本脚本不使用）")
    args = parser.parse_args()

    _deploy_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..')
    _xlsx_file = find_xlsx(_deploy_dir)
    if not _xlsx_file or not os.path.exists(_xlsx_file):
        logger.error("xlsx file not found in lib/odmp/")
        sys.exit(1)

    _systems = load_system_names(_xlsx_file)
    if not _systems:
        logger.error("未从 xlsx 加载到 Biz_system 系统名称")
        sys.exit(1)

    _mockdata_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    success = run(
        system_names=_systems,
        start=args.start,
        end=args.end,
        debug=args.debug,
        mockdata_dir=_mockdata_dir,
    )
    sys.exit(0 if success else 1)
