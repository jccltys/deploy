# -*- coding: utf-8 -*-
"""ODMP API 工具集 — 采集层初始化流程"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from core.config_utils import load_config_file
from tools._odmp_api._base import (
    _logger, _ensure_console_handler, _parse_jar_name_version,
    BASE_INGESTION, BASE_MODELING, BASE_WORKFLOW,
    scan_packages, scan_workflow_resources, _CLICKHOUSE_PRIVATE_KEY,
    BaseAPI,
)


class IngestionFlow(BaseAPI):
    """采集层初始化流程"""

    def run(self, package_dir='.', list_only=False, builtin_only=False,
            local_only=False, logger=None):
        if logger is None:
            _ensure_console_handler()
            logger = _logger

        package_dir = os.path.abspath(package_dir)

        if list_only:
            self._list_builtin_jars(logger)
            return

        infra = load_config_file()
        if not infra:
            logger.warning('未找到 config.yaml，基础设施配置不可用')

        # 第 1 步：数据中心
        logger.info('=== 第 1 步：创建数据中心 ===')
        dc_id = self._find_data_center_id('EOI')
        if dc_id:
            logger.info('数据中心 "EOI" 已存在，ID: %s', dc_id)
        else:
            dc_id = self._create_data_center('EOI')
            logger.info('数据中心 "EOI" 创建成功，ID: %s', dc_id)

        # 第 2 步：注册中心
        rc_id = None
        nacos = infra.get('nacos') if infra else None
        if nacos:
            logger.info('=== 第 2 步：创建注册中心 (nacos=%s) ===', nacos['addr'])
            rc_id = self._find_register_center_id('EOI')
            if rc_id:
                logger.info('注册中心 "EOI" 已存在，ID: %s', rc_id)
            else:
                rc_id = self._create_register_center(dc_id, nacos['addr'], nacos['password'])
                logger.info('注册中心 "EOI" 创建成功，ID: %s', rc_id)
        else:
            logger.info('=== 第 2 步：注册中心（跳过，未找到 nacos 配置）===')

        # 第 3 步：数据源
        logger.info('=== 第 3 步：创建数据源 ===')
        self._create_datasources(infra, dc_id, rc_id, logger)

        # 第 4 步：集群
        cluster_name = 'pson'
        logger.info('检查集群 "%s" ...', cluster_name)
        cluster_id = self._find_cluster_id(cluster_name)
        if not cluster_id:
            logger.info('集群不存在，正在创建...')
            result = self._create_cluster(cluster_name)
            if result.get('code') != '0000':
                raise RuntimeError('创建集群失败: {}'.format(result.get('msg', '未知错误')))
            cluster_id = result.get('data', {}).get('id', '')
            logger.info('集群创建成功，ID: %s', cluster_id)
        else:
            logger.info('集群已存在，ID: %s', cluster_id)

        # 第 5 步：创建存储集群（在导入算子包之前）
        logger.info('=== 第 5 步：创建存储集群 ===')
        try:
            kafka_ds_id = self.find_ds_id('KAFKA')
            ck_ds_id = self.find_ds_id('CLICKHOUSE')
            if kafka_ds_id and ck_ds_id and rc_id and cluster_id:
                opts_id = self._query_marayarn_ck_opts_id(logger)
                if opts_id:
                    self._create_storage_cluster(
                        kafka_ds_id, ck_ds_id, rc_id, cluster_id, opts_id, logger)
                else:
                    logger.warning('未找到 Marayarn_CK opts，跳过存储集群创建')
            else:
                logger.warning('缺少必要数据源或注册中心/集群，跳过存储集群创建')
        except RuntimeError as e:
            logger.warning('存储集群创建失败: %s（可后续手动创建）', e)

        # 第 6 步：创建业务分类（算子包导入前置依赖）
        logger.info('=== 第 6 步：创建业务分类 ===')
        try:
            biz_cat_id = self._create_business_category(logger)
            logger.info('业务分类 ID: %s', biz_cat_id)
        except RuntimeError as e:
            logger.warning('业务分类创建失败: %s（可后续手动创建）', e)

        # 第 7 步：创建业务流（workflow 资源上传前置依赖）
        logger.info('=== 第 7 步：创建业务流 ===')
        business_flow_id = None
        try:
            business_flow_id = self._create_business_flow()
            logger.info('业务流创建成功，ID: %s', business_flow_id)
        except RuntimeError as e:
            logger.warning('业务流创建失败: %s（可后续手动创建）', e)

        # 第 8 步：注册内置算子包
        if not local_only:
            self._register_builtin_jars(cluster_id, logger)

        # 第 9 步：上传本地非内置算子包
        if not builtin_only:
            self._upload_local_packages(cluster_id, package_dir, logger)

        # 第 10 步：上传 workflow 资源包
        if not builtin_only and business_flow_id:
            self._upload_workflow_resources(cluster_id, business_flow_id, package_dir, logger)
        elif not business_flow_id:
            logger.warning('业务流未创建，跳过 workflow 资源上传')

        # 第 11 步：创建授权管理客户端
        logger.info('=== 第 11 步：创建授权管理客户端 ===')
        try:
            self._create_client()
            logger.info('授权管理客户端创建成功')
        except RuntimeError as e:
            logger.warning('授权管理客户端创建失败: %s（可后续手动创建）', e)

        logger.info('=== 初始化完成 ===')

    def _create_data_center(self, name='EOI'):
        url = self._url(BASE_INGESTION, '/data/center')
        payload = {'name': name}
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建数据中心失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', {}).get('id', '')

    def _find_data_center_id(self, name='EOI'):
        url = self._url(BASE_INGESTION, '/data/center/query')
        payload = {'page': 0, 'size': 500, 'filter': {}, 'sort': {}}
        result = self._request_json(url, data=payload)
        for item in result.get('data', []):
            if item.get('name') == name:
                return item.get('id')
        return None

    def _create_register_center(self, data_center_id, address, password,
                                name='EOI', nacos_type='NACOS', namespace='public',
                                username='nacos', status='NORMAL'):
        urls = [u.strip() for u in address.split(',')]
        connect_detail = json.dumps({
            'status': status, 'normalUrls': urls,
            'abnormalUrlMap': {}, 'errMsg': None,
        }, ensure_ascii=False)
        payload = {
            'type': nacos_type, 'name': name, 'address': urls[0],
            'namespace': namespace, 'username': username, 'password': password,
            'dataCenterIds': [data_center_id],
            'connectDetail': connect_detail, 'status': status,
        }
        url = self._url(BASE_INGESTION, '/register-center')
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建注册中心失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', {}).get('id', '')

    def _find_register_center_id(self, name='EOI'):
        url = self._url(BASE_INGESTION, '/register-center/query')
        payload = {'page': 0, 'size': 10, 'filter': {}, 'sort': {'updateTime': 'DESC'}}
        result = self._request_json(url, data=payload)
        for item in result.get('data', []):
            if item.get('name') == name:
                return item.get('id')
        return None

    def _create_datasource(self, data_center_id, platform, name, code,
                           param_map, status='NORMAL', connect_mode='MANUAL',
                           connect_detail=None, register_center_id=None):
        payload = {
            'name': name, 'code': code, 'dataCenterIds': [data_center_id],
            'paramMap': param_map, 'platform': platform,
            'connectMode': connect_mode, 'status': status,
        }
        if register_center_id:
            payload['registerCenterId'] = register_center_id
        if connect_detail:
            payload['connectDetail'] = connect_detail
        url = self._url(BASE_INGESTION, '/datasource')
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建数据源失败 ({}): {}'.format(platform, result.get('msg', '未知错误')))
        return result.get('data', {}).get('id', '')

    def _create_datasources(self, infra, dc_id, rc_id, logger):
        if not infra:
            return
        if 'mysql' in infra:
            mysql = infra['mysql']
            for ds_name, ds_code, url_tpl in (
                ('mysql_odmp', 'mysql_odmp', 'jdbc:mysql://{}:{}/odmp'),
                ('mysql_refiner_pro', 'mysql_refiner_pro', 'jdbc:mysql://{}:{}/refiner_pro'),
            ):
                addr = url_tpl.format(mysql['host'], mysql['port'])
                try:
                    self._create_datasource(dc_id, 'MYSQL', ds_name, ds_code,
                                            {'address': addr, 'username': 'root',
                                             'password': mysql['password']},
                                            status='ABNORMAL')
                    logger.info('  数据源 %s 创建成功', ds_name)
                except Exception as e:
                    logger.warning('  数据源 %s 失败: %s', ds_name, e)
        if 'redis' in infra:
            redis = infra['redis']
            sentinel_servers = redis.get('sentinel_servers', '')
            if sentinel_servers:
                params = {
                    'mode': 'sentinel',
                    'address': sentinel_servers,
                    'password': redis['password'],
                    'masterName': redis.get('sentinel_name', 'mymaster'),
                }
            else:
                addr = '{}:{}'.format(redis['host'], redis['port'])
                params = {
                    'mode': 'single',
                    'address': addr,
                    'password': redis['password'],
                }
            try:
                self._create_datasource(dc_id, 'REDIS', 'redis', 'redis', params)
                logger.info('  数据源 redis 创建成功')
            except Exception as e:
                logger.warning('  数据源 redis 失败: %s', e)
        if 'kafka' in infra:
            kafka = infra['kafka']
            broker_addrs = ','.join('{}:{}'.format(h, kafka['port']) for h in kafka['hosts'])
            try:
                self._create_datasource(dc_id, 'KAFKA', 'kafka', 'kafka',
                                        {'brokerAddress': broker_addrs,
                                         'securityProtocol': 'PLAINTEXT'})
                logger.info('  数据源 kafka 创建成功')
            except Exception as e:
                logger.warning('  数据源 kafka 失败: %s', e)
        if 'nebula' in infra:
            nebula = infra['nebula']
            graphd_addr = '{}:{}'.format(nebula['host'], nebula['graphd_port'])
            meta_addr = '{}:{}'.format(nebula['host'], nebula['meta_port'])
            try:
                self._create_datasource(dc_id, 'NEBULA', 'nebula', 'nebula', {
                    'address': graphd_addr, 'metaAddress': meta_addr,
                    'username': 'root', 'password': 'root',
                }, connect_detail=json.dumps({
                    'status': 'NORMAL', 'normalUrls': [graphd_addr, meta_addr],
                    'abnormalUrlMap': {}, 'errMsg': None,
                }, ensure_ascii=False))
                logger.info('  数据源 nebula 创建成功')
            except Exception as e:
                logger.warning('  数据源 nebula 失败: %s', e)
        if 'clickhouse' in infra and rc_id:
            ck = infra['clickhouse']
            ckman_addr = '{}:{}'.format(ck['ckman_host'], ck['ckman_port'])
            try:
                self._create_datasource(dc_id, 'CLICKHOUSE', 'clickhouse', 'clickhouse', {
                    'registerCenterId': rc_id,
                    'privateKey': _CLICKHOUSE_PRIVATE_KEY,
                    'ckClusterName': ck['cluster'],
                    'ckUsername': 'default',
                    'ckPassword': ck['password'],
                    'jdbcProp': {'compress_algorithm': 'gzip', 'database': 'odmp',
                                 'socket_timeout': '600000'},
                    'nacosGroupName': 'DEFAULT_GROUP',
                }, connect_mode='NACOS_3RD',
                   connect_detail=json.dumps({
                       'status': 'NORMAL', 'normalUrls': [ckman_addr],
                       'abnormalUrlMap': {}, 'errMsg': None,
                   }, ensure_ascii=False))
                logger.info('  数据源 clickhouse 创建成功')
            except Exception as e:
                logger.warning('  数据源 clickhouse 失败: %s', e)
        elif 'clickhouse' in infra and not rc_id:
            logger.warning('  数据源 clickhouse 跳过（需要注册中心）')

    def _create_cluster(self, cluster_name):
        url = self._url(BASE_INGESTION, '/cluster')
        payload = {
            'clusterName': cluster_name, 'clusterType': 'yarn',
            'flinkOptsId': '6', 'sparkOptsId': '2', 'marayarnOptsId': '9',
            'defaultFlinkCluster': True, 'defaultSparkCluster': True,
            'defaultMarayarnCluster': True,
            'setting': {
                'hadoopHome': '${JAX_HOME}/hadoop',
                'pythonEnv': '/data/apps/odmp/pyenv',
                'webKrb5Enabled': 'false', 'timeoutMs': 300000,
            },
        }
        return self._request_json(url, data=payload)

    def _find_cluster_id(self, cluster_name):
        url = self._url(BASE_INGESTION, '/cluster/query?fetchResourcePool=false')
        payload = {'size': 100, 'page': 0, 'filter': {}, 'sort': {'updateTime': 'DESC'}}
        result = self._request_json(url, data=payload)
        for item in result.get('data', []):
            if item.get('clusterName') == cluster_name:
                return item['id']
        return None

    def _list_builtin_jars(self, logger):
        logger.info('查询已上传的内置算子包...')
        try:
            url = self._url(BASE_INGESTION, '/jar-build-in')
            result = self._request_json(url, method='GET')
            data = result.get('data', [])
            if not data:
                logger.info('暂无已上传的内置算子包')
            else:
                logger.info('已上传的内置算子包 (%d 个):', len(data))
                for jar_file in data:
                    name, ver = _parse_jar_name_version(jar_file)
                    logger.info('  %-40s  %-12s  %s', jar_file, name, ver)
        except Exception as e:
            logger.error('查询失败: %s', e)
            raise RuntimeError('查询内置算子包列表失败') from e

    def _register_builtin_jars(self, cluster_id, logger):
        logger.info('=== 第 6 步：注册内置算子包 ===')
        try:
            url = self._url(BASE_INGESTION, '/jar-build-in')
            builtin_result = self._request_json(url, method='GET')
            builtin_list = builtin_result.get('data', [])
        except Exception as e:
            logger.error('查询内置算子包列表失败: %s', e)
            raise RuntimeError('查询内置算子包列表失败') from e
        if not builtin_list:
            logger.info('无可注册的内置算子包')
            return
        logger.info('共 %d 个内置算子包，开始注册...', len(builtin_list))
        bk_ok = bk_fail = 0
        builtin_jax = [f for f in builtin_list if f.startswith('jax')]
        skipped = len(builtin_list) - len(builtin_jax)
        if skipped:
            logger.info('跳过非 jax 开头的内置包: %d 个', skipped)
        for jar_file in builtin_jax:
            jar_name, jar_ver = _parse_jar_name_version(jar_file)
            jar_type = 'jar' if jar_file.endswith('.jar') else 'python'
            if not jar_name:
                bk_fail += 1
                continue
            try:
                url = self._url(BASE_INGESTION, '/jar-build-in')
                data = urllib.parse.urlencode({
                    'jarBuildFile': jar_file, 'jarName': jar_name,
                    'jarVersion': jar_ver, 'jarFile': jar_file,
                    'jarDescription': jar_name, 'clusterId': cluster_id,
                    'jarType': jar_type,
                }).encode('ascii')
                req = urllib.request.Request(url, data=data, method='POST')
                req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                req.add_header('Accept', 'application/json')
                try:
                    resp = urllib.request.urlopen(req, timeout=120)
                    result = json.loads(resp.read().decode('utf-8'))
                except urllib.error.HTTPError as e:
                    msg = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
                    raise RuntimeError('注册内置算子失败 (HTTP {}): {}'.format(e.code, msg[:500]))
                except urllib.error.URLError as e:
                    raise RuntimeError('注册内置算子失败: {}'.format(e.reason))
                if result.get('code') == '0000':
                    logger.info('  [%12s] %-30s %s ... OK', jar_type, jar_name, jar_ver)
                    bk_ok += 1
                else:
                    logger.error('  [%12s] %-30s %s ... FAIL: %s',
                                 jar_type, jar_name, jar_ver, result.get('msg', '未知错误'))
                    bk_fail += 1
            except Exception as e:
                logger.error('  [%12s] %-30s %s ... ERROR: %s', jar_type, jar_name, jar_ver, e)
                bk_fail += 1
        logger.info('内置算子注册完成: %d 成功, %d 失败', bk_ok, bk_fail)

    def _upload_local_packages(self, cluster_id, package_dir, logger):
        logger.info('=== 第 7 步：上传本地非内置算子包 ===')
        entries = scan_packages(package_dir)
        if not entries:
            logger.warning('在 %s/job/{jar,python,data} 下未找到算子包', package_dir)
            return
        logger.info('找到 %d 个算子包，开始上传...', len(entries))
        ok = fail = 0
        for fpath, jar_type in entries:
            fname = os.path.basename(fpath)
            try:
                filename = os.path.basename(fpath)
                jar_name, jar_version = _parse_jar_name_version(filename)
                url = self._url(BASE_INGESTION, '/jar')
                fields = {
                    'jarName': jar_name, 'jarVersion': jar_version,
                    'jarFile': filename, 'jarDescription': jar_name,
                    'clusterId': cluster_id, 'jarType': jar_type,
                }
                result = self._upload_file(url, fpath, fields, file_field_name='file')
                if result.get('code') == '0000':
                    logger.info('  [%12s] %s ... OK', jar_type, fname)
                    ok += 1
                else:
                    logger.error('  [%12s] %s ... FAIL: %s', jar_type, fname,
                                 result.get('msg', '未知错误'))
                    fail += 1
            except Exception as e:
                logger.error('  [%12s] %s ... ERROR: %s', jar_type, fname, e)
                fail += 1
        logger.info('本地算子上传完成: %d 成功, %d 失败', ok, fail)

    def _upload_workflow_resources(self, cluster_id, business_flow_id, package_dir,
                                   logger):
        logger.info('=== 第 10 步：上传 workflow 资源包 ===')
        entries = scan_workflow_resources(package_dir)
        if not entries:
            logger.warning('在 %s/job/workflow/ 下未找到资源包', package_dir)
            return
        logger.info('找到 %d 个 workflow 资源包，开始上传...', len(entries))
        ok = fail = skip = 0
        for fpath in entries:
            fname = os.path.basename(fpath)
            try:
                url = self._url(BASE_WORKFLOW, '/resource')
                fields = {
                    'alias': fname,
                    'description': '离线流任务同步CMDB资源包',
                    'clusterId': cluster_id,
                    'businessFlowId': business_flow_id,
                }
                result = self._upload_file(url, fpath, fields, file_field_name='file')
                if result.get('code') == '0000':
                    logger.info('  %s ... OK', fname)
                    ok += 1
                else:
                    msg = result.get('msg', '')
                    if '资源名已存在' in msg:
                        logger.info('  %s ... 已存在，跳过', fname)
                        skip += 1
                    else:
                        logger.error('  %s ... FAIL: %s', fname, msg)
                        fail += 1
            except RuntimeError as e:
                emsg = str(e)
                if '资源名已存在' in emsg:
                    logger.info('  %s ... 已存在，跳过', fname)
                    skip += 1
                else:
                    logger.error('  %s ... ERROR: %s', fname, emsg)
                    fail += 1
        logger.info('workflow 资源上传完成: %d 成功, %d 跳过, %d 失败', ok, skip, fail)

    def _create_business_flow(self, name='AIOPS'):
        url = self._url(BASE_INGESTION, '/business-flow')
        payload = {'name': name}
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建业务流失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', {}).get('id', '')

    def _create_client(self, name='AIOPS', api_key='fullmonitor',
                       secret_key='fullmonitor', verify_secret=False):
        url = 'http://{}/api/v2/data-service/client'.format(self.api_addr)
        payload = {
            'name': name, 'apiKey': api_key,
            'secretKey': secret_key, 'verifySecret': verify_secret,
        }
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建客户端失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', {}).get('id', '')

    def _query_marayarn_ck_opts_id(self, logger=None):
        """查询 Marayarn_CK 的 optsId"""
        if logger is None:
            logger = _logger
        url = self._url(BASE_INGESTION, '/opts/query')
        payload = {'size': 20, 'page': 0, 'filter': {}, 'sort': {'updateTime': 'DESC'}}
        try:
            result = self._request_json(url, data=payload)
            if result.get('code') != '0000':
                logger.warning('查询 opts 列表失败: %s', result.get('msg'))
                return None
            for item in result.get('data', []):
                if item.get('optsName') == 'Marayarn_CK':
                    opts_id = item.get('id')
                    logger.info('Marayarn_CK optsId: %s', opts_id)
                    return opts_id
            logger.warning('未找到 Marayarn_CK opts')
            return None
        except Exception as e:
            logger.warning('查询 opts 异常: %s', e)
            return None

    def _create_storage_cluster(self, kafka_ds_id, ck_ds_id, register_center_id,
                                cluster_id, opts_id, logger=None):
        """创建存储集群（指标集群）"""
        if logger is None:
            logger = _logger
        name = '指标集群'
        logger.info('创建存储集群 "%s" ...', name)
        url = self._url(BASE_INGESTION, '/storage-cluster')
        payload = {
            'name': name,
            'kafkaDsId': kafka_ds_id,
            'ckDsId': ck_ds_id,
            'registerCenterId': register_center_id,
            'nacosGroupName': 'SINKER_GROUP',
            'taskLimit': 0,
            'clusterId': cluster_id,
            'optsId': opts_id,
            'instanceNum': 1,
            'ckMaxConnection': 1,
            'cpuNum': 1,
            'memory': 1024,
        }
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建存储集群失败: {}'.format(result.get('msg', '未知错误')))
        logger.info('存储集群 "%s" 创建成功，ID: %s', name, result.get('data', {}).get('id'))

    def _create_business_category(self, logger, code='aiops', name='一体化运维'):
        cat_id = self._find_category_id(code=code)
        if cat_id:
            logger.info('业务分类 "%s" 已存在，ID: %s', code, cat_id)
            return cat_id
        url = self._url(BASE_MODELING, '/business-category')
        payload = {'code': code, 'name': name, 'parentId': None}
        logger.info('创建业务分类 "%s" (%s) ...', name, code)
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建业务分类失败: {}'.format(result.get('msg', '未知错误')))
        cat_id = result.get('data', {}).get('id', '')
        logger.info('业务分类创建成功，ID: %s', cat_id)
        return cat_id

    def _find_category_id(self, code='aiops'):
        url = self._url(BASE_MODELING, '/business-category/tree')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询业务分类树失败: {}'.format(result.get('msg', '未知错误')))
        for item in result.get('data', []):
            if item.get('code') == code:
                return item.get('id')
        return None
