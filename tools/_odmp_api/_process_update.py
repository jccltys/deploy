# -*- coding: utf-8 -*-
"""ODMP API 工具集 — 数据处理任务配置更新流程"""
import datetime
import re

from core.config_utils import load_config_file
from tools._odmp_api._base import (
    _logger,
    BASE_INGESTION, BASE_DATA_MODELING,
    BaseAPI,
)
from tools._odmp_api._import_flow import ImportFlow


class DataProcessUpdateFlow(BaseAPI):
    """数据处理任务配置更新流程"""

    def run(self, logger=None):
        log = logger or _logger

        log.info('--- Step 1: 查询业务流 ID ---')
        flows = self.query_business_flows()
        business_flow_id = ImportFlow._find_business_flow_id(flows, name='AIOPS')
        if not business_flow_id:
            raise RuntimeError('未找到 BIZFLOW 节点，无法获取 businessFlowId')
        log.info('业务流 ID: %s', business_flow_id)

        log.info('--- Step 2: 查询数据开发任务列表 ---')
        url = self._url(BASE_INGESTION, '/business-flow-tree/query-list')
        result = self._request_json(url, data={
            'size': 100,
            'filter': {'businessFlowId': business_flow_id},
        })
        if result.get('code') != '0000':
            raise RuntimeError('查询业务流失败: {}'.format(result.get('msg', '未知错误')))
        tasks = result.get('data', [])

        streaming_tasks = []
        skipped = []
        for t in tasks:
            task_type = t.get('type', '')
            if task_type == 'STORAGE_CK':
                skipped.append(t)
            elif task_type == 'streaming':
                streaming_tasks.append(t)
            else:
                log.info('忽略未知 type 任务: %s (type=%s)', t.get('name', ''), task_type)
        if skipped:
            log.info('跳过 %d 个 STORAGE_CK 类型任务: %s', len(skipped),
                     ', '.join(t.get('name', '') for t in skipped))

        if not streaming_tasks:
            log.info('没有需要更新配置的任务')
            return

        log.info('--- Step 3: 加载基础设施配置 ---')
        infra = load_config_file()
        if not infra:
            raise RuntimeError('未找到 config.yaml 或解析失败')

        log.info('--- Step 4: 查询指标来源映射 ---')
        metric_sources = self._query_metric_sources(log)

        log.info('--- Step 5: 查询集群 ID ---')
        cluster_id = self._query_cluster_id(log)

        log.info('--- Step 6: 更新 %d 个 streaming 任务配置 ---', len(streaming_tasks))
        success = 0
        fail = 0
        for task in streaming_tasks:
            ref_id = task.get('referenceId')
            name = task.get('name', '')
            if not ref_id:
                log.warning('[%s] 节点无 referenceId，跳过', name)
                continue
            try:
                self._update_task(ref_id, name, infra, metric_sources, cluster_id, log)
                success += 1
            except Exception as e:
                log.error('[%s] 更新失败: %s', name, e)
                fail += 1

        log.info('--- 更新完成: %d 成功, %d 失败 ---', success, fail)

    @staticmethod
    def _find_data_processing_tasks(flows):
        return [item for item in flows if item.get('category') == 'REAL_TIME_DATA_PROCESSING']

    def _query_metric_sources(self, log):
        url = self._url(BASE_DATA_MODELING, '/metric-source/query')
        result = self._request_json(url, data={
            'size': 100, 'page': 0, 'filter': {}, 'sort': {'updateTime': 'DESC'},
        })
        if result.get('code') != '0000':
            log.warning('查询指标来源失败: %s', result.get('msg'))
            return {}
        sources = result.get('data', [])
        mapping = {}
        for s in sources:
            name = s.get('name')
            sid = s.get('id')
            if name and sid:
                mapping[name] = sid
        log.info('指标来源映射: %s', mapping)
        return mapping

    def _query_cluster_id(self, log):
        url = self._url(BASE_INGESTION, '/cluster/query')
        result = self._request_json(url, data={})
        if result.get('code') != '0000':
            log.warning('查询集群列表失败: %s', result.get('msg'))
            return None
        clusters = result.get('data', [])
        if not clusters:
            log.warning('集群列表为空')
            return None
        cid = clusters[0].get('id')
        log.info('集群 ID: %s (%s)', cid, clusters[0].get('clusterName'))
        return cid

    @staticmethod
    def _get_metric_source_name(task_name):
        if '听云-指标-标准化' in task_name:
            return '听云'
        elif 'APM指标' in task_name:
            return 'APM'
        elif '优云' in task_name:
            return '优云'
        else:
            return '基础监控'

    def _update_task(self, ref_id, task_name, infra, metric_sources, cluster_id, log):
        get_url = self._url(BASE_INGESTION, '/process/{}'.format(ref_id))
        result = self._request_json(get_url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('获取详情失败: {}'.format(result.get('msg', '未知错误')))

        process = result.get('data', {})
        if not process:
            raise RuntimeError('响应中无数据')

        modified = self._modify_process(process, infra, task_name, metric_sources, cluster_id, log)
        if not modified:
            log.info('[%s] 配置无需修改', task_name)
            return

        put_url = self._url(BASE_INGESTION, '/process/{}'.format(ref_id))
        put_result = self._request_json(put_url, data=process, method='PUT')
        if put_result.get('code') != '0000':
            raise RuntimeError('更新失败: {}'.format(put_result.get('msg', '未知错误')))
        log.info('[%s] 配置更新成功', task_name)

    def _modify_process(self, process, infra, task_name, metric_sources, cluster_id, log):
        kafka_cfg = infra.get('kafka', {})
        kafka_hosts = kafka_cfg.get('hosts', [])
        kafka_port = kafka_cfg.get('port', 9092)
        kafka_servers = ['{}:{}'.format(h, kafka_port) for h in kafka_hosts]

        mysql_cfg = infra.get('mysql', {})
        mysql_host = mysql_cfg.get('host', '127.0.0.1')
        mysql_port = mysql_cfg.get('port', 3306)
        mysql_password = mysql_cfg.get('password', 'MySQL@123')
        mysql_ds_url = 'jdbc:mysql://{}:{}/odmp?characterEncoding=utf8&useSSL=false'.format(
            mysql_host, mysql_port)

        ch_cfg = infra.get('clickhouse', {})
        ch_host = ch_cfg.get('host', ch_cfg.get('ckman_host', '127.0.0.1'))
        ch_http_port = ch_cfg.get('http_port', 18123)
        ch_password = ch_cfg.get('password', 'ck@123')
        ch_jdbc_url = 'jdbc:clickhouse://{}:{}/odmp'.format(ch_host, ch_http_port)

        today = datetime.datetime.now().strftime('%Y%m%d')
        modified = False

        if cluster_id and process.get('clusterId') != cluster_id:
            log.info('  [%s] clusterId: %s -> %s', task_name, process.get('clusterId'), cluster_id)
            process['clusterId'] = cluster_id
            modified = True

        jobs = process.get('pipelineConfig', {}).get('jobs', [])
        for job in jobs:
            job_config = job.get('jobConfig', {})
            job_name = job.get('jobName', '')
            job_display = job.get('jobDisplay', '')

            if job_name.endswith('.KafkaByteSourceJob'):
                if 'bootstrapServers' in job_config:
                    old = job_config['bootstrapServers']
                    if old != kafka_servers:
                        log.info('  [%s] bootstrapServers: %s -> %s', task_name, old, kafka_servers)
                        job_config['bootstrapServers'] = kafka_servers
                        modified = True
                topics = job_config.get('topics', [])
                if topics:
                    new_group_id = '{}_{}'.format(topics[0], today)
                    old_group = job_config.get('groupId', '')
                    if old_group != new_group_id:
                        log.info('  [%s] groupId: %s -> %s', task_name, old_group, new_group_id)
                        job_config['groupId'] = new_group_id
                        modified = True
                version = '1.12' if '_1.12' in job_display else '1.9'
                new_opts_id = '6' if version == '1.12' else '4'
                if process.get('optsId') != new_opts_id:
                    log.info('  [%s] optsId: %s -> %s', task_name, process.get('optsId'), new_opts_id)
                    process['optsId'] = new_opts_id
                    modified = True

            elif job_name.endswith('.KafkaSinkJob') and 'bootstrapServers' in job_config:
                old = job_config['bootstrapServers']
                if old != kafka_servers:
                    log.info('  [%s] KafkaSink bootstrapServers: %s -> %s', task_name, old, kafka_servers)
                    job_config['bootstrapServers'] = kafka_servers
                    modified = True

            elif job_name == 'com.eoi.jax.flink.job.process.SingleMetricBindJob':
                if 'dataSourceUrl' in job_config:
                    old = job_config['dataSourceUrl']
                    if old != mysql_ds_url:
                        log.info('  [%s] dataSourceUrl: %s -> %s', task_name, old, mysql_ds_url)
                        job_config['dataSourceUrl'] = mysql_ds_url
                        modified = True
                if 'password' in job_config:
                    old = job_config['password']
                    if old != mysql_password:
                        log.info('  [%s] SingleMetricBindJob password: %s -> %s', task_name, old, mysql_password)
                        job_config['password'] = mysql_password
                        modified = True
                if 'metricSourceId' in job_config:
                    src_name = DataProcessUpdateFlow._get_metric_source_name(task_name)
                    target_id = metric_sources.get(src_name)
                    if target_id and job_config['metricSourceId'] != target_id:
                        log.info('  [%s] metricSourceId: %s -> %s (来源: %s)',
                                 task_name, job_config['metricSourceId'], target_id, src_name)
                        job_config['metricSourceId'] = target_id
                        modified = True

            elif job_name == 'com.eoi.jax.flink.job.process.JdbcEnrichJob':
                if 'jdbcUrl' in job_config:
                    old = job_config['jdbcUrl']
                    if ch_jdbc_url not in old:
                        log.info('  [%s] jdbcUrl: %s -> %s', task_name, old, ch_jdbc_url)
                        job_config['jdbcUrl'] = ch_jdbc_url
                        modified = True
                if 'password' in job_config:
                    old = job_config['password']
                    if old != ch_password:
                        log.info('  [%s] JdbcEnrichJob password: %s -> %s', task_name, old, ch_password)
                        job_config['password'] = ch_password
                        modified = True
                if 'sql' in job_config:
                    new_sql = re.sub(r'`([^`]+)`\.', '`odmp`.', job_config['sql'])
                    if new_sql != job_config['sql']:
                        log.info('  [%s] sql 库名已替换为 odmp', task_name)
                        job_config['sql'] = new_sql
                        modified = True

        return modified
