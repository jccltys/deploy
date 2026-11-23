# -*- coding: utf-8 -*-
"""ODMP API 工具集 — 系统管理配置初始化流程"""
from tools._odmp_api._base import (
    _logger, _ensure_console_handler,
    BASE_SYSTEM, BASE_MODELING, BASE_INGESTION,
    BaseAPI,
)


class ConfigFlow(BaseAPI):
    """系统管理配置初始化流程"""

    def run(self, zk_connect=None, logger=None):
        if logger is None:
            _ensure_console_handler()
            logger = _logger

        ck_database = 'odmp'
        nebula_space = 'cmdb'

        logger.info('系统管理配置开始: api=%s', self.api_addr)

        logger.info('=== 第 1 步：获取数据源 ID ===')
        ck_ds_id = self.find_ds_id('CLICKHOUSE')
        nebula_ds_id = self.find_ds_id('NEBULA')
        redis_ds_id = self.find_ds_id('REDIS')
        logger.info('  ClickHouse 数据源 ID: %s', ck_ds_id)
        logger.info('  Nebula 数据源 ID: %s', nebula_ds_id)
        logger.info('  Redis 数据源 ID: %s', redis_ds_id)

        logger.info('=== 第 2 步：获取数仓分层/业务分类/业务过程/数据域 ID ===')
        layers = self._get_warehouse_layers()
        dwd_layer_id = None
        for l in layers:
            if l.get('name') == '明细数据层':
                dwd_layer_id = l.get('id')
                logger.info('  数仓分层(明细数据层) ID: %s', dwd_layer_id)
                break

        cats = self._get_business_category_tree()
        biz_id = None
        for c in cats:
            if c.get('code') == 'aiops':
                biz_id = c.get('id')
                logger.info('  业务分类(aiops) ID: %s', biz_id)
                break

        procs = self._query_business_processes()
        proc_id = None
        dom_id = None
        for p in procs:
            if p.get('domName') == '配置域':
                proc_id = p.get('id')
                logger.info('  业务过程(配置域) ID: %s', proc_id)
                break

        domains = self._get_domain_list()
        for d in domains:
            if d.get('name') == '配置域':
                dom_id = d.get('id')
                logger.info('  数据域(配置域) ID: %s', dom_id)
                break

        logger.info('=== 第 3 步：开始修改系统配置 ===')

        self._update_config_safe('6', {
            'enable': True,
            'connectString': zk_connect,
            'namespace': 'jax-dolphinscheduler',
            'maxRetries': 5,
        }, logger=logger)

        if redis_ds_id:
            self._update_config_safe('2', {
                'enable': True, 'database': 0, 'connectionPoolSize': 20,
            }, ds_id=redis_ds_id, logger=logger)
        else:
            logger.warning('  配置 [2] 跳过（未找到 Redis 数据源）')

        if all([dwd_layer_id, biz_id, proc_id, dom_id]):
            self._update_config_safe('9', {
                'layerId': int(dwd_layer_id),
                'bizId': int(biz_id),
                'procId': int(proc_id),
                'domId': int(dom_id),
            }, logger=logger)
        else:
            logger.warning('  配置 [9] 跳过（缺少必要 ID）')

        if ck_ds_id:
            self._update_config_safe('18', {
                'cmdbOdsTable': '{}.ods_cmdb_object'.format(ck_database),
                'cmdbOdsRelationTable': '{}.ods_cmdb_object_relation'.format(ck_database),
                'cmdbExcelMiddleTable': '{}.ods_cmdb_excel_import'.format(ck_database),
                'cmdbWideTable': '{}.dwd_cmdb_object_all'.format(ck_database),
                'cmdbRelationWideTable': '{}.dwd_cmdb_object_relation_all'.format(ck_database),
                'importLogTable': '{}.dwd_cmdb_object_import_history'.format(ck_database),
            }, ds_id=ck_ds_id, logger=logger)
        else:
            logger.warning('  配置 [18] 跳过（未找到 ClickHouse 数据源）')

        if nebula_ds_id:
            self._update_config_safe('19', {
                'baseSpace': nebula_space,
                'imageSpace': nebula_space,
                'relationEdge': 'cmdb_object_relation',
            }, ds_id=nebula_ds_id, logger=logger)
        else:
            logger.warning('  配置 [19] 跳过（未找到 Nebula 数据源）')

        logger.info('=== 系统管理配置完成 ===')

    def _list_configs(self):
        url = self._url(BASE_SYSTEM, '/list')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询系统配置列表失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', {})

    def _update_config(self, config_id, setting, ds_id=None):
        payload = {'id': config_id, 'dsId': ds_id, 'setting': setting}
        url = self._url(BASE_SYSTEM, '/{}'.format(config_id))
        result = self._request_json(url, data=payload, method='PUT')
        if result.get('code') != '0000':
            raise RuntimeError('修改系统配置 {} 失败: {}'.format(config_id, result.get('msg', '未知错误')))
        return result

    def _update_config_safe(self, config_id, setting, ds_id=None, logger=None):
        if logger is None:
            logger = _logger
        prefix = '  配置 [{}]'.format(config_id)
        logger.info('%s 开始...', prefix)
        try:
            self._update_config(config_id, setting, ds_id=ds_id)
            logger.info('%s ... OK', prefix)
        except RuntimeError as e:
            logger.warning('%s ... FAIL: %s', prefix, e)

    def _get_warehouse_layers(self):
        url = self._url(BASE_MODELING, '/warehouse-layer/list')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询数仓分层失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])

    def _get_business_category_tree(self):
        url = self._url(BASE_MODELING, '/business-category/tree')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询业务分类树失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])

    def _query_business_processes(self):
        url = self._url(BASE_MODELING, '/bus-process/query')
        result = self._request_json(url, data={
            'size': 50, 'page': 0, 'filter': {},
            'sort': {'updateTime': 'DESC'},
        })
        if result.get('code') != '0000':
            raise RuntimeError('查询业务过程失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])

    def _get_domain_list(self):
        url = self._url(BASE_MODELING, '/domain/list')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询数据域列表失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])
