# -*- coding: utf-8 -*-
"""ODMP API 工具集 — 建模层导入流程"""
import os

from tools._odmp_api._base import (
    _logger, _ensure_console_handler, _type_cn, _PUBLISH_TYPE_MAP,
    CATEGORY_CODE, CATEGORY_NAME,
    BASE_MODELING, BASE_DATA_SERVICE, BASE_INGESTION,
    scan_import_files, scan_import_files_by_keyword,
    BaseAPI,
)
from tools.odmp_publish import TablePublisher, ObjectPublisher, ApiPublisher


class ImportFlow(BaseAPI):
    """建模层导入流程"""

    def run(self, import_dir='lib/odmp/', mode='cover', logger=None, zk_connect=None,
            install_dir='/data'):
        if logger is None:
            _ensure_console_handler()
            logger = _logger

        import_dir = os.path.abspath(import_dir)

        logger.info('=== 第 1 步：获取业务分类 ===')
        biz_cat_id = self._find_category_id('aiops')
        if not biz_cat_id:
            logger.warning('业务分类 aiops 不存在（IngestionFlow 未执行或创建失败），跳过关联')
        else:
            logger.info('业务分类 ID: %s', biz_cat_id)

        logger.info('=== 第 2 步：扫描导入文件 ===')
        entries = scan_import_files(import_dir)
        if not entries:
            logger.warning('在 %s 下未找到匹配的 xlsx 文件', import_dir)
            raise RuntimeError('未找到匹配的 xlsx 文件')
        logger.info('找到 %d 个待导入文件:', len(entries))
        for fpath, itype in entries:
            logger.info('  [%s] %s', _type_cn(itype), os.path.basename(fpath))

        logger.info('=== 第 3 步：创建 API 分组 ===')
        self._create_api_groups(logger)

        # 分离 dataDomain 与其他类型
        dd_entries = [(f, t) for f, t in entries if t == 'dataDomain']
        other_entries = [(f, t) for f, t in entries if t != 'dataDomain']

        # 第 4 步：导入 dataDomain
        logger.info('=== 第 4 步：导入数据域 (dataDomain) ===')
        has_error = False
        if dd_entries:
            for fpath, itype in dd_entries:
                try:
                    result = self._import_excel(fpath, itype, mode=mode)
                    if result.get('code') != '0000':
                        has_error = True
                except Exception as e:
                    logger.error('文件 %s [%s] 异常: %s',
                                 os.path.basename(fpath), _type_cn(itype), e)
                    has_error = True
        else:
            logger.info('未找到 dataDomain 导入文件')

        # 第 5 步：关联数据域到业务分类
        logger.info('=== 第 5 步：关联数据域到业务分类 (id=%s) ===', biz_cat_id)
        try:
            self._link_domains_to_category(biz_cat_id)
            logger.info('数据域关联成功')
        except Exception as e:
            logger.warning('数据域关联失败: %s', e)

        # 第 6 步：系统管理配置初始化
        if zk_connect:
            logger.info('=== 第 6 步：系统管理配置初始化 ===')
            try:
                from tools.odmp_api import ConfigFlow
                cfg = ConfigFlow(self.api_addr)
                cfg.run(zk_connect=zk_connect, logger=logger)
                logger.info('系统管理配置初始化完成')
            except Exception as e:
                logger.warning('系统管理配置初始化异常: %s', e)
        else:
            logger.info('=== 第 6 步：系统管理配置初始化（跳过，未提供 zk_connect）===')

        # 第 7 步：导入其余类型
        has_flexible_job = any(t == 'flexibleJob' for _, t in other_entries)
        logger.info('=== 第 7 步：导入其余类型 (mode=%s) ===', mode)
        if other_entries:
            has_error = self._import_files(other_entries, mode, logger, import_dir=import_dir) or has_error
        else:
            logger.info('无其他类型文件需要导入')

        # 第 8 步：更新数据处理任务配置
        logger.info('=== 第 8 步：更新数据处理任务配置 ===')
        try:
            from tools.odmp_api import DataProcessUpdateFlow
            dp = DataProcessUpdateFlow(self.api_addr)
            dp.run(logger=logger)
        except Exception as e:
            logger.warning('数据处理任务配置更新异常: %s（可后续手动执行 process 命令）', e)

        # 第 9 步：如果有 flexibleJob 导入，更新弹性作业配置
        if has_flexible_job:
            logger.info('=== 第 9 步：更新弹性作业配置 ===')
            try:
                from tools.odmp_api import JobUpdateFlow
                jf = JobUpdateFlow(self.api_addr)
                jf.run(install_dir=install_dir, logger=logger)
            except Exception as e:
                logger.warning('弹性作业配置更新异常: %s（可后续手动执行 job 命令）', e)
        else:
            logger.info('=== 第 9 步：更新弹性作业配置（跳过，未导入 flexibleJob）===')

        if has_error:
            raise RuntimeError('部分文件导入存在失败行')

    def _create_business_category(self, logger, code=CATEGORY_CODE, name=CATEGORY_NAME):
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

    def _find_category_id(self, code=CATEGORY_CODE):
        url = self._url(BASE_MODELING, '/business-category/tree')
        result = self._request_json(url, method='GET')
        if result.get('code') != '0000':
            raise RuntimeError('查询业务分类树失败: {}'.format(result.get('msg', '未知错误')))
        for item in result.get('data', []):
            if item.get('code') == code:
                return item.get('id')
        return None

    def _find_api_group(self, name):
        url = self._url(BASE_DATA_SERVICE, '/api-group/api-tree/query')
        result = self._request_json(url, data={'apiName': ''})
        if result.get('code') != '0000':
            raise RuntimeError('查询 API 分组树失败: {}'.format(result.get('msg', '未知错误')))
        def _search(items):
            if not items:
                return None
            for item in items:
                if item.get('name') == name:
                    return item.get('id')
                if 'children' in item:
                    found = _search(item['children'])
                    if found:
                        return found
            return None
        return _search(result.get('data', []))

    def _create_api_group(self, name):
        url = self._url(BASE_DATA_SERVICE, '/api-group')
        payload = {'name': name}
        _logger.info('创建 API 分组 "%s" ...', name)
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('创建 API 分组失败: {}'.format(result.get('msg', '未知错误')))
        group_id = result.get('data', {}).get('id', '')
        _logger.info('API 分组 "%s" 创建成功，ID: %s', name, group_id)
        return group_id

    def _create_api_groups(self, logger):
        for group_name in ('全息监控', '标准数据服务'):
            try:
                existing_id = self._find_api_group(group_name)
                if existing_id:
                    logger.info('API 分组 "%s" 已存在，ID: %s', group_name, existing_id)
                else:
                    self._create_api_group(group_name)
            except RuntimeError as e:
                logger.warning('API 分组 "%s" 操作失败: %s', group_name, e)

    def _import_excel(self, file_path, import_type, mode='cover', file_field_name='excelFile',
                      **extra_params):
        filename = os.path.basename(file_path)
        cn = _type_cn(import_type)
        extra_qs = '&'.join('{}={}'.format(k, v) for k, v in extra_params.items() if v is not None)
        url = '{}?type={}&mode={}{}'.format(
            self._url(BASE_MODELING, '/excel/import'), import_type, mode,
            '&' + extra_qs if extra_qs else '')
        _logger.info('导入 [%s] %s (type=%s, mode=%s) ...', cn, filename, import_type, mode)
        result = self._upload_file(url, file_path, file_field_name=file_field_name)
        if result.get('code') == '0000':
            data = result.get('data', {})
            status = data.get('importStatus', 'UNKNOWN')
            ok = data.get('successRow', 0)
            fail = data.get('failedRow', 0)
            if fail:
                _logger.warning('文件 %s [%s] 导入完成: 成功 %d 行, 失败 %d 行 (status=%s)',
                                filename, cn, ok, fail, status)
            else:
                _logger.info('文件 %s [%s] 导入完成: 成功 %d 行, 失败 %d 行 (status=%s)',
                             filename, cn, ok, fail, status)
        else:
            _logger.error('文件 %s [%s] 导入失败: %s', filename, cn, result.get('msg', ''))
        return result

    def _run_post_import_publish(self, import_type, logger):
        pub_type = _PUBLISH_TYPE_MAP.get(import_type)
        if not pub_type:
            return
        try:
            publishers = {
                'table': TablePublisher,
                'object': ObjectPublisher,
                'api': ApiPublisher,
            }
            cls = publishers[pub_type]
            pub = cls(self.api_addr)
            logger.info('触发 %s 模型发布...', _type_cn(import_type))
            total, ok, fail = pub.publish_all(logger=logger)
            if fail:
                logger.warning('%s 模型发布完成: %d 成功, %d 失败',
                               _type_cn(import_type), ok, fail)
            else:
                logger.info('%s 模型发布完成: %d 个全部成功',
                            _type_cn(import_type), total)
        except Exception as e:
            logger.warning('%s 模型发布异常: %s（可后续手动发布）',
                           _type_cn(import_type), e)

    def _import_files(self, entries, mode, logger, import_dir=None):
        if import_dir is not None:
            dd_entries = scan_import_files_by_keyword(
                import_dir, 'dataDevelopment', extensions={'.zip'})
            if dd_entries:
                logger.info('找到 %d 个开发任务文件:', len(dd_entries))
                for fpath, _ in dd_entries:
                    logger.info('  %s', os.path.basename(fpath))
                entries = list(entries) + dd_entries

        flow_id = None
        has_error = False
        for fpath, import_type in entries:
            try:
                extra_params = {}
                if import_type == 'dataDevelopment':
                    if flow_id is None:
                        flow_id = self._query_business_flow_id(logger)
                    if flow_id:
                        extra_params['flowId'] = flow_id
                    else:
                        logger.warning('未能获取业务流 flowId，跳过开发任务 %s',
                                       os.path.basename(fpath))
                        has_error = True
                        continue
                result = self._import_excel(fpath, import_type, mode=mode, **extra_params)
                if result.get('code') == '0000':
                    data = result.get('data', {})
                    if data.get('failedRow', 0):
                        has_error = True
                    else:
                        self._run_post_import_publish(import_type, logger)
                else:
                    has_error = True
            except Exception as e:
                logger.error('文件 %s [%s] 异常: %s',
                             os.path.basename(fpath), _type_cn(import_type), e)
                has_error = True
        return has_error

    def _link_domains_to_category(self, biz_category_id):
        url = self._url(BASE_MODELING,
                        '/data-domain/business-category-many/{}'.format(biz_category_id))
        result = self._request_json(url, data={})
        if result.get('code') != '0000':
            raise RuntimeError('关联数据域失败: {}'.format(result.get('msg', '未知错误')))
        return result

    @staticmethod
    def _find_business_flow_id(flows, name=None):
        for f in flows:
            if f.get('nodeType') == 'BIZFLOW':
                if name is None or f.get('nodeName') == name:
                    return f.get('nodeId')
            children = f.get('children')
            if children:
                found = ImportFlow._find_business_flow_id(children, name=name)
                if found:
                    return found
        return None

    def _query_business_flow_id(self, logger=None):
        if logger is None:
            logger = _logger
        try:
            flows = self.query_business_flows()
            flow_id = self._find_business_flow_id(flows, name='AIOPS')
            if flow_id:
                logger.info('业务流 flowId: %s', flow_id)
            else:
                logger.warning('业务流树中未找到 BIZFLOW 节点')
            return flow_id
        except Exception as e:
            logger.warning('查询业务流树异常: %s', e)
            return None
