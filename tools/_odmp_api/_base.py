# -*- coding: utf-8 -*-
"""
ODMP API 工具集 — 基础模块

包含共享常量、工具函数和 BaseAPI 基类。
"""
import io
import json
import logging
import os
import re
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request

_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_TOOLS_DIR, '..'))

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)


def _ensure_console_handler():
    """确保 _logger 有控制台 handler（time-only 格式），避免重复添加"""
    if not any(isinstance(h, logging.StreamHandler)
               and h.stream == sys.stderr
               for h in _logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
        _logger.addHandler(handler)
        _logger.propagate = False


_TYPE_CN_MAP = {
    'dataDomain': '数据域',
    'businessProcess': '业务流过程',
    'enum': '数据字典',
    'measure': '度量单位',
    'table': '维度建模',
    'object': '对象模型',
    'objectIndicatorGroup': '指标模型',
    'objectRelationPath': '关系路径',
    'objectInstance': '对象关系',
    'api': '数据服务',
    'flexibleJob': '弹性作业',
    'businessCategory': '业务分类',
    'dataDevelopment': '开发任务',
    'dimLabel': '维度标签',
}

BASE_INGESTION = '/api/v2/ingestion'
BASE_MODELING = '/api/v2/data/modeling'
BASE_DATA_MODELING = '/api/v2/data-modeling'
BASE_DATA_SERVICE = '/api/v2/data-service'
BASE_SYSTEM = '/api/v2/systemconfig'
BASE_WORKFLOW = '/api/v2/workflow'

CATEGORY_CODE = 'aiops'
CATEGORY_NAME = '一体化运维'
VALID_MODES = ('skip', 'cover')
_FILE_PATTERN = re.compile(r'(\d+)[-_](\w+)[-_](\w+)_(\d+)\.xlsx$')


def _type_cn(t):
    return _TYPE_CN_MAP.get(t, t)


def _parse_jar_name_version(filename):
    base = filename
    for ext in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.zip', '.jar', '.tar'):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    m = re.search(r'(\d+\.\d+\.\d+)', base)
    if not m:
        return base, ''
    version = m.group(1)
    idx = base.find(version)
    name = base[:idx].rstrip('-_')
    return name, version


def scan_packages(install_dir):
    entries = []
    for sub_dir, jar_type in (('jar', 'jar'), ('python', 'python'), ('data', 'api_handler')):
        scan_path = os.path.join(install_dir, 'job', sub_dir)
        if not os.path.isdir(scan_path):
            continue
        for f in sorted(os.listdir(scan_path)):
            fpath = os.path.join(scan_path, f)
            if os.path.isfile(fpath):
                entries.append((fpath, jar_type))
    return entries


def scan_workflow_resources(install_dir):
    scan_path = os.path.join(install_dir, 'job', 'workflow')
    if not os.path.isdir(scan_path):
        return []
    entries = []
    for f in sorted(os.listdir(scan_path)):
        fpath = os.path.join(scan_path, f)
        if os.path.isfile(fpath):
            entries.append(fpath)
    return entries


def scan_import_files(import_dir):
    if not os.path.isdir(import_dir):
        _logger.warning('导入目录不存在: %s', import_dir)
        return []
    entries = []
    for f in sorted(os.listdir(import_dir)):
        fpath = os.path.join(import_dir, f)
        if not os.path.isfile(fpath):
            continue
        m = _FILE_PATTERN.match(f)
        if not m:
            continue
        entries.append((fpath, m.group(3)))
    return entries


def scan_import_files_by_keyword(import_dir, keyword, extensions=None):
    """按关键词扫描导入文件"""
    if not os.path.isdir(import_dir):
        return []
    entries = []
    for f in sorted(os.listdir(import_dir)):
        if keyword not in f:
            continue
        fpath = os.path.join(import_dir, f)
        if not os.path.isfile(fpath):
            continue
        if extensions is not None:
            ext = os.path.splitext(f)[1].lower()
            if ext not in extensions:
                continue
        entries.append((fpath, keyword))
    return entries


def _setup_logger():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return root


_CLICKHOUSE_PRIVATE_KEY = (
    'MIICdwIBADANBgkqhkiG9w0BAQEFAASCAmEwggJdAgEAAoGBAL0gBFpckY8s4uxWodUIj3EtKdrgRopZ'
    'TqccRQ4cW9gb0tssyb2HoNjxcmwL+J47jBFlypCdQ5u6GbjZKzuUN/Va+z1xRlpSXOe3r6JvLR6HCP+K'
    'SnrundHs2PKDQsLEBucklgr3z9wW4qbWHnHriJRvmBi9QvRiv3NIXDaD7tnxAgMBAAECgYEAsIyB48TE'
    'UQ7K62tX+WHbXgCWMO/qid4i0VdPk4OfrVcT+GyQC3DgE4UZlol6VmQqNld6yJM2eNo6htecRyrvLG4F'
    'wLQcWIBqJQySoyYeekKLQVsnYU4vGjvA92E8cUHfnTJ/ZSTUFLRDinzCMRvL4mHaINVQSizBTAnZpA3e'
    'qAECQQDhxQRX71uJGAP8v9bEJy5jvdidhGxYFaQLfUik4rDxkOr+4RaNSWGAcKLfPrfk6zHvXbp6UkKZ'
    'sk7uMpj42WSBAkEA1nLj5m6DcUFI6lfzonrpnCvsiaQhvOOXPsMpNoNPFdBvgOeACIVCSv2QQUD0+N1f'
    'XRjz243/iDhEic7WqKb9cQJAN/rb+tnUvod/5ZnDrNtyOzUFkvkUzDqBdH/aFVhIO32NZyl0qA+751cG'
    'a4hnnJFczldVN6NR9D4sKA/PslRlAQJBAJAOw+vTB3d4TLwn8yGOAgqIMzDPUl6qYLqnrbLSCLl1uMHW'
    'Qdr3ce4gYdyD/0yCoYJPtdkijar7aYdNrEPFUfECQCxkn830hLKQM9GCdEkJEI3bW6UqzoUWweExul1A'
    'D5R9E8wKvjkBSUaaTuyQQpxw/xqJBveMYWJmNiKKQxSG72A='
)

_PUBLISH_TYPE_MAP = {
    'table':  'table',
    'object': 'object',
    'api':    'api',
}


class BaseAPI:
    """ODMP API 基类 — 共享的 HTTP 工具和通用查询方法"""

    def __init__(self, api_addr):
        self.api_addr = api_addr

    def _url(self, base, path):
        return 'http://{}{}{}'.format(self.api_addr, base, path)

    def _request_json(self, url, data=None, method='POST', timeout=30):
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Content-Type', 'application/json')
        req.add_header('Accept', 'application/json')
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8') if e.fp else str(e)
            raise RuntimeError('HTTP {}: {}'.format(e.code, msg))
        except urllib.error.URLError as e:
            raise RuntimeError('请求失败: {}'.format(e.reason))

    def _upload_file(self, url, file_path, fields=None, file_field_name='file'):
        boundary = '----' + uuid.uuid4().hex
        body = io.BytesIO()
        crlf = b'\r\n'

        def _w(s):
            body.write(s.encode('utf-8') if isinstance(s, str) else s)
            body.write(crlf)

        def _part_header(name, filename=None):
            body.write(b'--' + boundary.encode() + crlf)
            if filename:
                _w('Content-Disposition: form-data; name="{}"; filename="{}"'.format(name, filename))
                _w('Content-Type: application/octet-stream')
            else:
                _w('Content-Disposition: form-data; name="{}"'.format(name))
            _w('')

        if fields:
            for key, value in fields.items():
                _part_header(key)
                _w(value)

        filename = os.path.basename(file_path)
        _part_header(file_field_name, filename)
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                body.write(chunk)
        _w('')
        body.write(b'--' + boundary.encode() + b'--' + crlf)

        req_data = body.getvalue()
        req = urllib.request.Request(
            url, data=req_data, method='POST',
            headers={'Content-Type': 'multipart/form-data; boundary=' + boundary},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
            raise RuntimeError('上传失败 (HTTP {}): {}'.format(e.code, msg[:500]))
        except urllib.error.URLError as e:
            raise RuntimeError('上传失败: {}'.format(e.reason))

    # ----- 通用查询 -----

    def query_datasources(self):
        url = self._url(BASE_INGESTION, '/datasource/query')
        payload = {'page': 0, 'size': 500, 'filter': {}, 'sort': {}}
        result = self._request_json(url, data=payload)
        if result.get('code') != '0000':
            raise RuntimeError('查询数据源失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])

    def find_ds_id(self, platform):
        ds_list = self.query_datasources()
        for ds in ds_list:
            if ds.get('platform') == platform and ds.get('status') == 'NORMAL':
                return ds.get('id')
        return None

    def query_business_flows(self):
        url = self._url(BASE_INGESTION, '/business-flow-tree/query')
        result = self._request_json(url, data={})
        if result.get('code') != '0000':
            raise RuntimeError('查询业务流失败: {}'.format(result.get('msg', '未知错误')))
        return result.get('data', [])
