#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODMP 模型发布工具

将已导入的模型发布上线。发布流程分两步:
  1. create_deploy() — 创建发布记录，生成默认建表脚本/配置
  2. deploy() — 执行发布

支持的模型类型:
  - TablePublisher:   维度建模发布（支持 CLICKHOUSE / KAFKA 双平台）
  - ObjectPublisher:  对象建模发布（预留）
   - ApiPublisher:     数据服务发布

命令行使:
  python3 deploy/tools/odmp_publish.py table --api 192.168.217.101:9900
  python3 deploy/tools/odmp_publish.py object --api 192.168.217.101:9900
  python3 deploy/tools/odmp_publish.py api --api 192.168.217.101:9900

代码调用:
  from tools.odmp_publish import TablePublisher
  pub = TablePublisher('192.168.217.101:9900')
  total, ok, fail = pub.publish_all()
"""
import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request

BASE_INGESTION = '/api/v2/ingestion'
BASE_MODELING = '/api/v2/data/modeling'
BASE_DATA_MODELING = '/api/v2/data-modeling'
BASE_DATA_SERVICE = '/api/v2/data-service'

_logger = logging.getLogger(__name__)


def _request_json(url, data=None, method='POST', timeout=30):
    """发送 HTTP JSON 请求并解析响应

    参数:
        url: 完整请求地址
        data: 请求体字典。为 None 时无 body，为 {} 时空对象
        method: HTTP 方法（默认 POST）
        timeout: 超时秒数

    返回:
        解析后的 JSON 响应字典

    异常:
        RuntimeError: HTTP 错误或网络不可达
    """
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
        raise RuntimeError('HTTP {}: {}'.format(e.code, msg))
    except urllib.error.URLError as e:
        raise RuntimeError('请求失败: {}'.format(e.reason))


class BasePublisher:
    """发布器基类，提供共享的查询方法和 URL 拼接

    所有发布器（维度建模、对象建模、数据服务）共用以下查询接口:
      - business-flow-tree/query: 获取业务流 ID
      - datasource/query: 获取数据源 ID (dsId)

    参数:
        api_addr: ODMP 服务地址，格式 ip:port
    """

    def __init__(self, api_addr):
        self.api_addr = api_addr

    def _url(self, base, path):
        return 'http://{}{}{}'.format(self.api_addr, base, path)

    # 查询接口 — 业务流

    def query_business_flows(self):
        """查询业务流树

        POST /api/v2/ingestion/business-flow-tree/query
        返回业务流层级数据，用于获取发布所需的业务流 ID。

        返回:
            业务流列表，每项含 id / name / children 等字段
        """
        url = self._url(BASE_INGESTION, '/business-flow-tree/query')
        result = _request_json(url, data={})
        if result.get('code') != '0000':
            raise RuntimeError('查询业务流失败: {}'.format(
                result.get('msg', '未知错误')))
        return result.get('data', [])

    # 查询接口 — 数据源

    def query_datasources(self):
        """查询数据源列表

        POST /api/v2/ingestion/datasource/query
        用于获取发布所需的数据源 ID (dsId)。

        请求参数:
            page: 页码（从 0 开始）
            size: 每页条数
            filter: 过滤条件
            sort: 排序

        返回:
            数据源列表，每项含 id / dsId / name / platform / status 等字段
        """
        url = self._url(BASE_INGESTION, '/datasource/query')
        payload = {'page': 0, 'size': 500, 'filter': {}, 'sort': {}}
        result = _request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('查询数据源失败: {}'.format(
                result.get('msg', '未知错误')))
        return result.get('data', [])


class TablePublisher(BasePublisher):
    """维度建模发布器

    维度建模（对应导入类型 table）的完整发布流程（两步）:
      1. create_deploy() — 创建发布记录，生成默认建表脚本/默认配置
      2. deploy() — 执行发布，应用建表脚本（CK）或创建 topic（Kafka）

    数据源按 platform 自动匹配（CLICKHOUSE / KAFKA），
    从 query_datasources() 中取 status=NORMAL 的第一个匹配项。

    参数:
        api_addr: ODMP 服务地址，格式 ip:port
    """

    # 查询接口 — 维度建模

    def query_tables(self):
        """查询维度建模列表

        POST /api/v2/data/modeling/table/query
        返回的 id 字段即 tbId，用于 create_deploy 调用。

        请求参数:
            page: 页码（从 0 开始）
            size: 每页条数
            filter: 过滤条件
            sort: 排序

        返回:
            维度建模条目列表，每项含 id / tbName / name / status 等字段。
            id 即是 tbId。
        """
        url = self._url(BASE_MODELING, '/table/query')
        payload = {'page': 0, 'size': 500, 'filter': {}, 'sort': {}}
        result = _request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('查询维度建模列表失败: {}'.format(
                result.get('msg', '未知错误')))
        return result.get('data', [])

    # 发布接口 — Step 1: 创建发布记录

    def create_deploy(self, platform, tb_id, tb_name, ds_id,
                      business_flow_id, setting_map, name=None):
        """创建发布记录

        POST /api/v2/data/modeling/table-deploy/
        服务端生成默认建表脚本（CK 返回 DDL，Kafka 返回空 script）
        并返回发布记录 ID，供 deploy() 第二步使用。

        参数:
            platform: 发布平台（CLICKHOUSE / KAFKA）
            tb_id: 维度建模 ID (来自 query_tables 的 id)
            tb_name: 表名 (tbName)
            ds_id: 数据源 ID (dsId，来自 query_datasources)
            business_flow_id: 业务流 ID
            setting_map: 平台特有参数
                CLICKHOUSE: {database, engine, distributed, shardingKey}
                KAFKA: {topicName, partition, replication, retention, ...}
            name: 发布名称，默认 {tbName}_{Platform}

        返回:
            API 响应字典（含 data.id 和 data.script）

        异常:
            RuntimeError: 创建失败
        """
        if name is None:
            name = '{}_{}'.format(tb_name, platform.capitalize())
        payload = {
            'platform': platform,
            'deployType': 'TABLE',
            'actionType': 'CREATE',
            'dsId': ds_id,
            'settingMap': setting_map,
            'tbId': tb_id,
            'tbName': tb_name,
            'businessFlowId': business_flow_id,
            'name': name,
        }
        url = self._url(BASE_MODELING, '/table-deploy')
        result = _request_json(url, data=payload, timeout=60)
        if result.get('code') != '0000':
            raise RuntimeError('创建发布记录失败 ({}): {}'.format(
                tb_name, result.get('msg', '未知错误')))
        return result

    # 发布接口 — Step 2: 执行发布

    def deploy(self, deploy_record_id, script, setting_map):
        """执行发布

        POST /api/v2/data/modeling/table-deploy/{deploy_record_id}/deploy

        CLICKHOUSE: 应用建表脚本（DDL）创建 ClickHouse 表
        KAFKA: 创建 Kafka topic（script 传空字符串）

        参数:
            deploy_record_id: 发布记录 ID（来自 create_deploy 返回的 data.id）
            script: 建表脚本（CK 用 DDL；Kafka 传空字符串）
            setting_map: 发布参数，同 create_deploy 中的 setting_map，
                         可在此覆盖（如 Kafka 可调整 retention）

        返回:
            API 响应字典

        异常:
            RuntimeError: 发布失败
        """
        payload = {
            'id': deploy_record_id,
            'script': script,
            'settingMap': setting_map,
        }
        url = self._url(BASE_MODELING, '/table-deploy/{}/deploy'.format(
            deploy_record_id))
        result = _request_json(url, data=payload, timeout=120)
        if result.get('code') != '0000':
            raise RuntimeError('发布失败 ({}): {}'.format(
                deploy_record_id, result.get('msg', '未知错误')))
        return result

    @staticmethod
    def _fix_dwd_script(script):
        """修正 dwd_cmdb_object_all 的建表脚本

        将 `properties` 的字段类型从 Nested(...) 改为 Map(String,String)，
        Nested 类型在 ClickHouse 中处理复杂，该表需要 map 类型。

        参数:
            script: 原始建表脚本字符串

        返回:
            修正后的建表脚本
        """
        return re.sub(
            r'(`properties`)\s+Nested\([^)]*\)',
            r'\1 Map(String,String)',
            script,
        )

    @staticmethod
    def _find_business_flow_id(flows, name=None):
        """从业务流树中提取业务流的 nodeId（即 flowId）

        参数:
            name: 业务流名称，传空则返回第一个 BIZFLOW 节点
        """
        for f in flows:
            if f.get('nodeType') == 'BIZFLOW':
                if name is None or f.get('nodeName') == name:
                    return f.get('nodeId')
            children = f.get('children')
            if children:
                found = TablePublisher._find_business_flow_id(children, name=name)
                if found:
                    return found
        return None

    # 全流程

    def publish_all(self, logger=None):
        """查询并向所有可用平台发布维度建模

        对每个维度建模条目，向可用的发布平台分别执行两步发布:
          1. create_deploy() — 创建发布记录，获取建表脚本/配置
          2. deploy() — 执行发布

        自动从数据源列表匹配：
          - platform=CLICKHOUSE 且 status=NORMAL 的数据源
          - platform=KAFKA    且 status=NORMAL 的数据源

        参数:
            logger: 日志记录器（可选，默认使用模块级 logger）

        返回:
            (total, ok, fail) 包含总数、成功数、失败数的元组
        """
        if logger is None:
            logger = _logger

        logger.info('维度建模发布开始')
        tables = self.query_tables()
        if not tables:
            logger.info('未找到维度建模数据')
            return 0, 0, 0

        logger.info('共查询到 %d 个维度建模', len(tables))

        # 获取数据源 → 按平台查找可用发布目标
        try:
            datasources = self.query_datasources()
            logger.info('获取到 %d 个数据源', len(datasources))
        except RuntimeError as e:
            logger.warning('查询数据源失败: %s', e)
            return 0, 0, 0

        ck_ds = next(
            (d for d in datasources
             if d.get('platform') == 'CLICKHOUSE' and d.get('status') == 'NORMAL'),
            None)
        kafka_ds = next(
            (d for d in datasources
             if d.get('platform') == 'KAFKA' and d.get('status') == 'NORMAL'),
            None)

        # 获取业务流 ID（根 BIZFLOW 节点的 nodeId）
        try:
            flows = self.query_business_flows()
            bf_id = self._find_business_flow_id(flows, name='AIOPS')
            if bf_id:
                logger.info('业务流 ID: %s', bf_id)
            else:
                logger.warning('未找到业务流节点')
        except RuntimeError as e:
            logger.warning('查询业务流失败: %s', e)
            bf_id = None

        # 配置各平台发布参数
        platforms = []
        if ck_ds:
            platforms.append({
                'platform': 'CLICKHOUSE',
                'dsId': ck_ds['id'],
                'settingMap': {
                    'database': 'odmp',
                    'engine': 'ReplicatedMergeTree',
                    'distributed': True,
                    'shardingKey': 'rand()',
                },
            })
        if kafka_ds:
            platforms.append({
                'platform': 'KAFKA',
                'dsId': kafka_ds['id'],
                # topicName 需在每个表发布时动态设置
                'settingMapBase': {
                    'partition': 3,
                    'replication': 1,
                    'retention': 1,
                    'retentionUnit': 'DAY',
                    'maxMessageBytes': 'DEFAULT',
                    'messageType': 'JSON',
                    'paramMap': {},
                },
            })

        if not platforms:
            logger.warning('未找到可用的 CLICKHOUSE 或 KAFKA 数据源，跳过发布')
            return 0, 0, 0

        total = 0
        ok = 0
        fail = 0

        for t in tables:
            tid = t.get('id')
            if not tid:
                logger.warning('跳过无 id 的条目')
                continue
            tb_name = t.get('tbName', '')
            tb_alias = t.get('tbAlias', '') or t.get('name', '')

            # 根据别名（tbAlias）后缀确定发布目标平台
            # 别名以 CK 结尾（忽略大小写）→ 只发布 CLICKHOUSE
            # 别名以 KAFKA 结尾（忽略大小写）→ 只发布 KAFKA
            # 其他 → 不发布
            alias_upper = tb_alias.upper()
            if alias_upper.endswith('CK'):
                plat_list = [p for p in platforms
                             if p['platform'] == 'CLICKHOUSE']
            elif alias_upper.endswith('KAFKA'):
                plat_list = [p for p in platforms
                             if p['platform'] == 'KAFKA']
            else:
                plat_list = []

            if not plat_list:
                logger.info('跳过 %s (%s)（别名 "%s" 规则过滤）',
                            tb_name, tid, tb_alias)
                continue

            for plat_conf in plat_list:
                p_name = plat_conf['platform']
                total += 1

                # 构造 settingMap（Kafka 需要动态设置 topicName）
                if p_name == 'KAFKA':
                    sm = dict(plat_conf['settingMapBase'])
                    sm['topicName'] = tb_name
                else:
                    sm = dict(plat_conf['settingMap'])
                    # 特例：glb_trans_details 表发布到 aimeter 库
                    if tb_name == 'glb_trans_details':
                        sm['database'] = 'aimeter'

                try:
                    # 第一步：创建发布记录
                    result = self.create_deploy(
                        platform=p_name,
                        tb_id=tid,
                        tb_name=tb_name,
                        ds_id=plat_conf['dsId'],
                        business_flow_id=bf_id or '',
                        setting_map=sm,
                    )
                    data = result.get('data', {})
                    deploy_id = data.get('id')
                    script = data.get('script', '')

                    if not deploy_id:
                        raise RuntimeError('创建发布记录返回无 id')

                    # 仅 CK 需要脚本修正（特殊表）
                    if p_name == 'CLICKHOUSE' \
                       and tb_name == 'dwd_cmdb_object_all' and script:
                        logger.info('检测到 %s (%s)，修正 properties 类型...',
                                    tb_name, tid)
                        script = self._fix_dwd_script(script)

                    # 第二步：执行发布
                    self.deploy(deploy_id, script, sm)

                    logger.info('发布成功: %s (%s) → %s', tb_name, tid, p_name)
                    ok += 1

                except RuntimeError as e:
                    logger.error('发布失败: %s (%s) → %s - %s',
                                 tb_name, tid, p_name, e)
                    fail += 1

        logger.info('维度建模发布完成: 总计 %d, 成功 %d, 失败 %d',
                    total, ok, fail)
        return total, ok, fail


class ObjectPublisher(BasePublisher):
    """对象建模发布器

    对象建模（对应导入类型 object）的完整发布流程（两步）:
      1. create_deploy() — 创建发布记录，生成默认建 Tag 脚本
      2. deploy() — 执行发布，在 Nebula Graph 中创建 Tag

    所有对象统一发布到 NEBULA 平台，不区分别名后缀。

    参数:
        api_addr: ODMP 服务地址，格式 ip:port
    """

    def __init__(self, api_addr):
        super().__init__(api_addr)
        # 从 config.yaml 读取 nebula 图空间名，默认 cmdb
        try:
            from deploy.core.config_utils import load_config_file
            infra = load_config_file()
            nebula_cfg = infra.get('nebula', {})
            self.space = nebula_cfg.get('space_name', 'cmdb')
        except (ImportError, IOError, OSError, AttributeError):
            self.space = 'cmdb'

    # 查询接口 — 对象建模

    def query_objects(self):
        """查询对象建模列表

        POST /api/v2/data-modeling/object-table/query
        返回的对象 id 即 tbId，用于 create_deploy 调用。

        请求参数:
            page: 页码（从 0 开始）
            size: 每页条数
            filter: 过滤条件
            sort: 排序

        返回:
            对象建模条目列表，每项含 id / tbName / name 等字段。
            id 即是 tbId。
        """
        url = self._url(BASE_DATA_MODELING, '/object-table/query')
        payload = {
            'size': 50,
            'page': 0,
            'filter': {'categoryId': ''},
            'sort': {'updateTime': 'DESC'},
        }
        result = _request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('查询对象建模列表失败: {}'.format(
                result.get('msg', '未知错误')))
        return result.get('data', [])

    # 发布接口 — Step 1: 创建发布记录

    def create_deploy(self, tb_id, tb_name, ds_id, business_flow_id):
        """创建对象模型发布记录

        POST /api/v2/data/modeling/table-deploy/
        服务端生成默认建 Tag 脚本（NEBULA DDL）并返回发布记录 ID。

        参数:
            tb_id: 对象建模 ID (来自 query_objects 的 id)
            tb_name: 对象表名 (tbName)
            ds_id: 数据源 ID (dsId，NEBULA 平台)
            business_flow_id: 业务流 ID

        返回:
            API 响应字典（含 data.id 和 data.script）
        """
        payload = {
            'platform': 'NEBULA',
            'deployType': 'TAG',
            'actionType': 'CREATE',
            'dsId': ds_id,
            'settingMap': {'space': self.space},
            'tbType': 'OBJ',
            'tbId': tb_id,
            'tbName': tb_name,
            'businessFlowId': business_flow_id,
            'name': '{}_Nebula'.format(tb_name),
        }
        url = self._url(BASE_MODELING, '/table-deploy')
        result = _request_json(url, data=payload, timeout=60)
        if result.get('code') != '0000':
            raise RuntimeError('创建对象发布记录失败 ({}): {}'.format(
                tb_name, result.get('msg', '未知错误')))
        return result

    # 发布接口 — Step 2: 执行发布

    def deploy(self, deploy_record_id, script):
        """执行对象模型发布

        POST /api/v2/data/modeling/table-deploy/{deploy_record_id}/deploy

        在 Nebula Graph 中执行建 Tag 脚本。

        参数:
            deploy_record_id: 发布记录 ID（来自 create_deploy 返回的 data.id）
            script: 建 Tag 脚本（NEBULA DDL，来自 create_deploy 返回的 data.script）

        返回:
            API 响应字典
        """
        payload = {
            'id': deploy_record_id,
            'script': script,
            'settingMap': {'space': self.space},
        }
        url = self._url(BASE_MODELING, '/table-deploy/{}/deploy'.format(
            deploy_record_id))
        result = _request_json(url, data=payload, timeout=120)
        if result.get('code') != '0000':
            raise RuntimeError('对象发布失败 ({}): {}'.format(
                deploy_record_id, result.get('msg', '未知错误')))
        return result

    # 全流程

    def publish_all(self, logger=None):
        """查询并向 NEBULA 平台发布所有对象建模

        对每个对象建模条目，执行两步发布:
          1. create_deploy() — 创建发布记录，获取建 Tag 脚本
          2. deploy() — 执行发布

        NEBULA 数据源从 query_datasources() 中自动匹配
        （platform=NEBULA 且 status=NORMAL）。

        参数:
            logger: 日志记录器（可选，默认使用模块级 logger）

        返回:
            (total, ok, fail) 包含总数、成功数、失败数的元组
        """
        if logger is None:
            logger = _logger

        logger.info('对象建模发布开始 (space=%s)', self.space)
        objects = self.query_objects()
        if not objects:
            logger.info('未找到对象建模数据')
            return 0, 0, 0

        logger.info('共查询到 %d 个对象建模', len(objects))

        # 获取 NEBULA 数据源
        try:
            datasources = self.query_datasources()
            logger.info('获取到 %d 个数据源', len(datasources))
        except RuntimeError as e:
            logger.warning('查询数据源失败: %s', e)
            return 0, 0, 0

        nebula_ds = next(
            (d for d in datasources
             if d.get('platform') == 'NEBULA' and d.get('status') == 'NORMAL'),
            None)
        if not nebula_ds:
            logger.warning('未找到可用的 NEBULA 数据源，跳过发布')
            return 0, 0, 0
        logger.info('NEBULA 数据源 ID: %s', nebula_ds['id'])

        # 获取业务流 ID
        try:
            flows = self.query_business_flows()
            bf_id = TablePublisher._find_business_flow_id(flows, name='AIOPS')
            if bf_id:
                logger.info('业务流 ID: %s', bf_id)
            else:
                logger.warning('未找到业务流节点')
        except RuntimeError as e:
            logger.warning('查询业务流失败: %s', e)
            bf_id = None

        total = 0
        ok = 0
        fail = 0

        for obj in objects:
            obj_id = obj.get('id')
            if not obj_id:
                logger.warning('跳过无 id 的条目')
                continue
            tb_name = obj.get('tbName', '')

            total += 1

            try:
                # 第一步：创建发布记录
                result = self.create_deploy(
                    tb_id=obj_id,
                    tb_name=tb_name,
                    ds_id=nebula_ds['id'],
                    business_flow_id=bf_id or '',
                )
                data = result.get('data', {})
                deploy_id = data.get('id')
                script = data.get('script', '')

                if not deploy_id:
                    raise RuntimeError('创建发布记录返回无 id')

                # 第二步：执行发布
                self.deploy(deploy_id, script)

                logger.info('发布成功: %s (%s) → NEBULA', tb_name, obj_id)
                ok += 1

            except RuntimeError as e:
                logger.error('发布失败: %s (%s) → NEBULA - %s',
                             tb_name, obj_id, e)
                fail += 1

        logger.info('对象建模发布完成: 总计 %d, 成功 %d, 失败 %d',
                    total, ok, fail)
        return total, ok, fail


class ApiPublisher(BasePublisher):
    """数据服务发布器

    数据服务的完整发布流程（两步）:
      1. publish() — 发布单个数据服务接口（草稿 → 已发布）
      2. online() — 批量上线已发布的数据服务接口

    参数:
        api_addr: ODMP 服务地址，格式 ip:port
    """

    def query_apis(self):
        """查询待发布的数据服务列表

        POST /api/v2/data-service/api/query
        过滤 status=DRAFT（草稿状态）的接口列表。

        请求参数:
            size: 每页条数
            page: 页码（从 0 开始）
            filter: 过滤条件（默认 status=DRAFT）
            sort: 排序

        返回:
            数据服务接口列表，每项含 id / name / apiPath / apiGroupId 等字段
        """
        url = self._url(BASE_DATA_SERVICE, '/api/query')
        payload = {
            'size': 100,
            'page': 0,
            'filter': {'status': 'DRAFT'},
            'sort': {},
        }
        result = _request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('查询数据服务列表失败: {}'.format(
                result.get('msg', '未知错误')))
        return result.get('data', [])

    def publish(self, api_id):
        """发布单个数据服务接口

        POST /api/v2/data-service/api/{api_id}/publish/single
        将草稿状态的数据服务接口发布为已发布状态。

        参数:
            api_id: 数据服务接口 ID

        返回:
            API 响应字典
        """
        url = self._url(BASE_DATA_SERVICE,
                        '/api/{}/publish/single'.format(api_id))
        result = _request_json(url, data={})
        if result.get('code') != '0000':
            raise RuntimeError('发布数据服务失败 ({}): {}'.format(
                api_id, result.get('msg', '未知错误')))
        return result

    def online(self, api_ids):
        """批量上线数据服务接口

        POST /api/v2/data-service/api/online

        参数:
            api_ids: 数据服务接口 ID 列表

        返回:
            API 响应字典
        """
        payload = {
            'apis': [{'id': aid} for aid in api_ids],
        }
        url = self._url(BASE_DATA_SERVICE, '/api/online')
        result = _request_json(url, data=payload, timeout=60)
        if result.get('code') != '0000':
            raise RuntimeError('上线数据服务失败: {}'.format(
                result.get('msg', '未知错误')))
        return result

    def publish_all(self, logger=None):
        """查询并发布所有草稿状态的数据服务

        流程:
          1. query_apis() — 查询草稿状态的数据服务
          2. publish() — 逐个发布（草稿 → 已发布）
          3. online() — 批量上线

        参数:
            logger: 日志记录器（可选，默认使用模块级 logger）

        返回:
            (total, ok, fail) 包含总数、成功数、失败数的元组
        """
        if logger is None:
            logger = _logger

        logger.info('数据服务发布开始')
        apis = self.query_apis()
        if not apis:
            logger.info('未找到待发布的数据服务')
            return 0, 0, 0

        logger.info('共查询到 %d 个待发布的数据服务接口', len(apis))

        total = 0
        ok = 0
        fail = 0
        published_ids = []

        for api in apis:
            api_id = api.get('id')
            if not api_id:
                logger.warning('跳过无 id 的条目')
                continue
            api_name = api.get('name', api.get('apiPath', ''))

            total += 1

            try:
                # 第一步：发布接口（草稿 → 已发布）
                self.publish(api_id)
                published_ids.append(api_id)
                logger.info('发布成功: %s (%s)', api_name, api_id)
                ok += 1

            except RuntimeError as e:
                logger.error('发布失败: %s (%s) - %s', api_name, api_id, e)
                fail += 1

        # 第二步：批量上线已发布的接口
        if published_ids:
            try:
                self.online(published_ids)
                logger.info('上线成功: %d 个数据服务接口', len(published_ids))
            except RuntimeError as e:
                logger.warning('上线失败: %s', e)

        logger.info('数据服务发布完成: 总计 %d, 成功 %d, 失败 %d',
                    total, ok, fail)
        return total, ok, fail


# CLI

_PUBLISHER_CLASSES = {
    'table':  (TablePublisher, '维度建模发布'),
    'object': (ObjectPublisher, '对象建模发布'),
    'api':    (ApiPublisher, '数据服务发布'),
}


def _setup_logger():
    """配置标准错误输出的日志"""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return root


def main():
    parser = argparse.ArgumentParser(
        description='ODMP 模型发布工具')
    parser.add_argument(
        'type', choices=list(_PUBLISHER_CLASSES.keys()),
        help='模型类型: ' + ', '.join(
            '{} - {}'.format(k, desc) for k, (_, desc) in _PUBLISHER_CLASSES.items()))
    parser.add_argument(
        '--api', required=True,
        help='ODMP API 地址，格式 ip:port，例如 192.168.217.101:9900')
    args = parser.parse_args()
    logger = _setup_logger()
    logger.info('模型发布工具启动: type=%s api=%s', args.type, args.api)

    cls, desc = _PUBLISHER_CLASSES[args.type]
    publisher = cls(args.api)

    try:
        total, ok, fail = publisher.publish_all(logger=logger)
        if fail:
            logger.warning('发布完成: 总计 %d, 成功 %d, 失败 %d', total, ok, fail)
            sys.exit(1)
        logger.info('发布完成: 全部成功 (%d/%d)', ok, total)
    except NotImplementedError as e:
        logger.error('功能未实现: %s', e)
        sys.exit(1)
    except RuntimeError as e:
        logger.error('发布失败: %s', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
