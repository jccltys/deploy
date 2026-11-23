# -*- coding: utf-8 -*-
"""ODMP API 工具集 — 弹性作业配置更新流程"""
import os

from core.config_utils import load_config_file
from tools._odmp_api._base import (
    _logger,
    BASE_INGESTION,
    BaseAPI,
)


class JobUpdateFlow(BaseAPI):
    """弹性作业配置更新流程"""
    NAME_CN = '弹性作业更新'

    def run(self, install_dir='/data', logger=None):
        log = logger or _logger

        log.info('=== %s ===', self.NAME_CN)

        log.info('--- Step 1: 加载基础设施配置 ---')
        infra = load_config_file()
        if not infra:
            raise RuntimeError('未找到 config.yaml 或解析失败')
        nacos = infra.get('nacos', {})
        if not nacos:
            raise RuntimeError('config.yaml 中未找到 nacos 配置')
        apps_dir = os.path.join(install_dir, 'apps')
        log.info('apps_dir: %s', apps_dir)

        log.info('--- Step 2: 查询弹性作业列表 ---')
        url = self._url(BASE_INGESTION, '/application/query')
        result = self._request_json(url, data={
            'size': 100, 'page': 0, 'filter': {}, 'sort': {'updateTime': 'DESC'},
        })
        if result.get('code') != '0000':
            raise RuntimeError('查询弹性作业失败: {}'.format(result.get('msg', '未知错误')))
        jobs = result.get('data', [])
        target = None
        for j in jobs:
            if j.get('name') == 'aimeter-alert':
                target = j
                break
        if not target:
            raise RuntimeError('未找到 name=aimeter-alert 的弹性作业')
        job_id = target.get('id')
        log.info('找到 aimeter-alert, ID: %s', job_id)

        log.info('--- Step 3: 获取弹性作业详情 ---')
        detail_url = self._url(BASE_INGESTION, '/application/{}'.format(job_id))
        detail_result = self._request_json(detail_url, method='GET')
        if detail_result.get('code') != '0000':
            raise RuntimeError('获取弹性作业详情失败: {}'.format(detail_result.get('msg', '未知错误')))
        detail = detail_result.get('data', {})
        setting_map = detail.get('settingMap', {})
        executor_env = setting_map.get('executorEnv', {})

        new_nacos_host = nacos.get('addr', '')
        new_nacos_password = nacos.get('password', '0192023A7BBD73250516F069DF18B500')
        modified = False

        log.info('--- Step 4: 更新 Nacos 地址 ---')
        if executor_env.get('NACOS_HOST') != new_nacos_host:
            log.info('  NACOS_HOST: %s -> %s', executor_env.get('NACOS_HOST'), new_nacos_host)
            executor_env['NACOS_HOST'] = new_nacos_host
            modified = True
        else:
            log.info('  NACOS_HOST 一致 (%s)', new_nacos_host)

        log.info('--- Step 5: 更新 Nacos 密码 ---')
        if executor_env.get('NACOS_PASSWORD') != new_nacos_password:
            log.info('  NACOS_PASSWORD: %s -> %s', executor_env.get('NACOS_PASSWORD'), new_nacos_password)
            executor_env['NACOS_PASSWORD'] = new_nacos_password
            modified = True
        else:
            log.info('  NACOS_PASSWORD 一致')

        log.info('--- Step 6: 更新 artifacts 路径 ---')
        current_artifacts = setting_map.get('artifacts', [])
        if current_artifacts:
            old_url = current_artifacts[0]
            pkg_name = old_url.rsplit('/', 1)[-1].rsplit('#', 1)[0] if '#' in old_url else old_url.rsplit('/', 1)[-1]
            new_artifacts_url = 'file://{}/aimeter/{}#app'.format(apps_dir, pkg_name)
            if old_url != new_artifacts_url:
                log.info('  artifacts: %s -> %s', old_url, new_artifacts_url)
                setting_map['artifacts'] = [new_artifacts_url]
                modified = True
            else:
                log.info('  artifacts 一致 (%s)', new_artifacts_url)
        else:
            log.info('  artifacts 为空，跳过')

        if not modified:
            log.info('配置无需修改')
            return

        log.info('--- Step 7: 提交更新 ---')
        put_payload = {
            'id': job_id,
            'name': detail.get('name'),
            'command': detail.get('command'),
            'description': detail.get('description'),
            'clusterId': detail.get('clusterId'),
            'optsId': detail.get('optsId'),
            'instanceCount': detail.get('instanceCount'),
            'settingMap': setting_map,
            'forceStart': False,
        }
        put_url = self._url(BASE_INGESTION, '/application/{}'.format(job_id))
        put_result = self._request_json(put_url, data=put_payload, method='PUT')
        if put_result.get('code') != '0000':
            raise RuntimeError('更新弹性作业失败: {}'.format(put_result.get('msg', '未知错误')))
        log.info('弹性作业配置更新成功')
