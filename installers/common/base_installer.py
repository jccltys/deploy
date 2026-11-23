# -*- coding: utf-8 -*-
"""
安装器基类 — 定义组件安装的标准流程和通用方法
子类继承后只需实现 generate_config / start_service 等特定逻辑
"""
import base64
import logging
import os
import posixpath
import re
import shlex
from string import Template

from core import config_utils


class DeployConfig(object):
    """只读配置（用户配置 + CLI 参数 + install.py 注入的只读数据）

    替代 namedtuple 以支持更灵活的字段管理，同时通过 __slots__ 防止动态添加属性。
    """
    __slots__ = (
        'install_dir', 'package_dir', 'config_template_dir', 'http_port',
        'comms_dir', 'apps_dir', 'debug', 'fail_fast', 'packages',
        'host_ip', 'deploy_log_dir', 'mysql_password', 'mysql_user',
        'java_env', 'nacos_password',
        'raw_config',             # 原始 YAML 配置完整字典
    )

    def __init__(self, install_dir, package_dir, config_template_dir, http_port,
                 comms_dir, apps_dir, debug, fail_fast, packages,
                 host_ip, deploy_log_dir, mysql_password, mysql_user,
                 java_env, nacos_password, raw_config):
        self.install_dir = install_dir
        self.package_dir = package_dir
        self.config_template_dir = config_template_dir
        self.http_port = http_port
        self.comms_dir = comms_dir
        self.apps_dir = apps_dir
        self.debug = debug
        self.fail_fast = fail_fast
        self.packages = packages
        self.host_ip = host_ip
        self.deploy_log_dir = deploy_log_dir
        self.mysql_password = mysql_password
        self.mysql_user = mysql_user
        self.java_env = java_env
        self.nacos_password = nacos_password
        self.raw_config = raw_config


class RuntimeContext(object):
    """可变运行时上下文（组件间共享状态）"""
    __slots__ = ('servers_map', 'comp_hosts', 'hostname_map',
                 'hadoop_master', 'broker_ids', 'zookeeper_connect', 'sudo_mode')

    def __init__(self):
        self.servers_map = {}
        self.comp_hosts = {}
        self.hostname_map = {}
        self.hadoop_master = ''
        self.broker_ids = {}
        self.zookeeper_connect = ''
        self.sudo_mode = {}


class ContextLogger(logging.LoggerAdapter):
    """为日志自动注入 component 和 host 上下文的适配器"""
    def process(self, msg, kwargs):
        kwargs['extra'] = kwargs.get('extra', {})
        kwargs['extra'].setdefault('component', self.extra['component'])
        kwargs['extra'].setdefault('host', self.extra['host'])
        return msg, kwargs


class BaseInstaller(object):
    """组件安装器基类，提供安装流程骨架和常用工具方法"""

    # 所属产品域分组（如 'common', 'sso' 等）
    # 子类覆盖此属性；None 表示无分组（向后兼容）
    GROUP = None

    # 部署模式：standard（默认分阶段/单机）/ cluster（组件自带集群入口）/ legacy（并行 install）
    DEPLOY_MODE = 'standard'
    # 部署前依赖开关
    REQUIRES_ZK_CHECK = False
    REQUIRES_HADOOP_CONF = False

    def __init__(self, ssh_client, config, context, logger):
        self.ssh = ssh_client      # SSH 远程客户端
        self.config = config       # 只读配置（DeployConfig namedtuple）
        self.ctx = context         # 可变运行时上下文（RuntimeContext）
        self.logger = ContextLogger(logger, {'component': self.name, 'host': ssh_client.host})
        # 从类属性读取分组信息，子类可设置 GROUP 覆盖
        self.group = getattr(self.__class__, 'GROUP', None)

    @classmethod
    def deploy_cluster(cls, hosts, servers_map, config, context, logger, results):
        """集群部署入口（仅 DEPLOY_MODE='cluster' 的组件覆盖）"""
        raise NotImplementedError

    @classmethod
    def post_deploy(cls, hosts, instances, servers_map, config, context, logger, results, failed):
        """健康检查通过后的后置初始化钩子（组件按需覆盖）"""
        pass

    @property
    def name(self):
        """组件名称：从类名自动推导（如 JavaInstaller → java）"""
        class_name = self.__class__.__name__
        if class_name.endswith('Installer'):
            return class_name[:-9].lower()
        return class_name.lower()

    @property
    def install_dir(self):
        return self.config.install_dir

    @property
    def comms_dir(self):
        """远程主机上的软件安装/解压目录"""
        return self.config.comms_dir

    @property
    def component_dir(self):
        """组件软链接路径（如 /data/service/comms/redis）"""
        return os.path.join(self.comms_dir, self.name)

    @property
    def apps_root(self):
        """App 类型安装器的容器目录（如 apps/sso/），组件包解压在此目录下"""
        return os.path.join(self.config.apps_dir, self.name)

    @property
    def _package_dest_dir(self):
        return self.comms_dir

    def _apps_component_symlink(self):
        """App 类型安装器的内部软链接路径（如 apps/sso/sso），指向 versioned 解压目录"""
        return os.path.join(self.apps_root, self.name)

    def _extract_version_rename(self, extracted_basename, extracted_path):
        return None

    @staticmethod
    def _extract_version_from_package(package_filename):
        """从包文件名提取版本号，如 'unified-authentication-3.2.1.tar.gz' → '3.2.1'"""
        base = package_filename
        for ext in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.zip', '.tar'):
            if base.endswith(ext):
                base = base[: -len(ext)]
                break
        m = re.search(r'(\d[\d.]*\d)', base)
        return m.group(1) if m else None

    @property
    def log_dir(self):
        """组件日志目录（如 /data/service/comms/redis/logs）"""
        return os.path.join(self.component_dir, 'logs')

    @property
    def data_dir(self):
        """组件数据目录（如 /data/service/comms/redis/data）"""
        return os.path.join(self.component_dir, 'data')

    @property
    def java_home(self):
        """组件使用的 JAVA_HOME 路径
        优先从 config.java_env 中读取该组件指定的 Java 版本；
        未配置时默认使用 comms_dir/java（JDK 8）。
        """
        java_env = getattr(self.config, 'java_env', {}) or {}
        java_version = java_env.get(self.name, 'java')
        return os.path.join(self.comms_dir, java_version)

    @property
    def package_file(self):
        """获取安装包文件名
        优先从 config.yaml 的 packages 中读取显式配置；
        未配置时自动在本地包目录中按组件名忽略大小写匹配归档文件。
        """
        packages = getattr(self.config, 'packages', {}) or {}
        if self.name in packages:
            return packages[self.name]

        # 自动发现：在本地包目录中匹配包含组件名的归档文件
        pkg_dir = getattr(self.config, 'package_dir', '') or ''
        if not pkg_dir or not os.path.isdir(pkg_dir):
            raise RuntimeError(
                '[{}] 未找到安装包目录: {}，请在 config.yaml 的 packages 中显式配置 {}'
                .format(self.name, pkg_dir, self.name)
            )

        # 当存在分组时，在分组子目录（如 softs/common/）下搜索
        search_dir = os.path.join(pkg_dir, self.group) if self.group else pkg_dir
        if not os.path.isdir(search_dir):
            raise RuntimeError(
                '[{}] 未找到安装包目录: {}，请在 --package-dir/{}/ 下放置 {} 的安装包'
                .format(self.name, search_dir, self.group or '.', self.name)
            )

        archive_exts = ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.zip', '.tar', '.rpm')
        pkg_name = getattr(self.__class__, 'PACKAGE_NAME', None) or self.name
        candidates = sorted(
            f for f in os.listdir(search_dir)
            if pkg_name.lower() in f.lower()
            and f.lower().endswith(archive_exts)
        )

        if not candidates:
            raise RuntimeError(
                '[{}] 在 {} 中未找到包含 "{}" 的安装包文件'
                .format(self.name, pkg_dir, self.name)
            )
        if len(candidates) > 1:
            self.logger.warning(
                '[%s] 发现多个匹配的安装包: %s，使用第一个: %s',
                self.name, candidates, candidates[0]
            )
        return candidates[0]

    @property
    def package_url(self):
        """构造 HTTP 下载 URL（有分组时含分组子目录路径）"""
        if self.group:
            return             'http://{}:{}/{}/{}'.format(
                self.config.host_ip,
                self.config.http_port,
                self.group,
                self.package_file
            )
        return 'http://{}:{}/{}'.format(
            self.config.host_ip,
            self.config.http_port,
            self.package_file
        )

    def template_vars(self, **overrides):
        """模板变量集合，供 render_configs 替换模板文件中的占位符"""
        vars = {
            'install_dir': self.install_dir,
            'comms_dir': self.comms_dir,
            'component_dir': self.component_dir,
            'log_dir': self.log_dir,
            'data_dir': self.data_dir,
            'host_ip': getattr(self.config, 'host_ip', '127.0.0.1'),
            'node_ip': self.ssh.host,
            'broker_id': '0',
            'zookeeper_connect': 'localhost:{}'.format(
                config_utils.get_port_from_config_or_template(
                    self.config, 'zookeeper', 'port',
                    'zookeeper/conf/zoo.cfg', [r'clientPort=(\d+)'], 2181)),
            'java_home': self.java_home,
            'mysql_password': getattr(self.config, 'mysql_password', 'MySQL@123'),
        }
        vars.update(overrides)
        return vars

    def prepare(self):
        """准备阶段：创建目录、下载安装包、解压、创建软链接、渲染配置、清理安装包（不包含启动）"""
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._create_data_dirs()
        self._rendered_files = []
        self.render_configs()
        self._save_config_snapshot()
        self._cleanup_package()

    def install(self, skip_health_check=False):
        """安装总入口：依次执行各步骤"""
        self.logger.info('[%s@%s] === 开始安装 ===', self.name, self.ssh.host)
        self.prepare()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self.logger.info('[%s@%s] === 安装完成 ===', self.name, self.ssh.host)

    @property
    def _config_snapshot_dir(self):
        deploy_log_dir = getattr(self.config, 'deploy_log_dir', '') or ''
        if not deploy_log_dir:
            return ''
        host_ip = self.ssh.host
        return os.path.join(deploy_log_dir, 'config-snapshots', self.name, host_ip)

    def _save_config_snapshot(self):
        snapshot_dir = self._config_snapshot_dir
        if not snapshot_dir or not self._rendered_files:
            return
        for rel_path, content in self._rendered_files:
            dest = os.path.join(snapshot_dir, os.path.basename(rel_path))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'w') as f:
                f.write(content)
        self.logger.info('[%s@%s] 配置文件快照已保存到: %s',
                         self.name, self.ssh.host, snapshot_dir)

    def _create_dirs(self):
        """创建远程主机上的安装目录（comms）"""
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.comms_dir)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.comms_dir)))

    def _create_data_dirs(self):
        """创建解压后的数据/日志目录，位于软链接（component_dir）下"""
        self.logger.info('[%s@%s] 创建数据/日志目录: %s, %s',
                          self.name, self.ssh.host, self.data_dir, self.log_dir)
        for d in [self.data_dir, self.log_dir]:
            self.ssh.execute('mkdir -p {}'.format(shlex.quote(d)))

    def upload_package(self):
        """从 HTTP 服务下载安装包到远程主机"""
        target = os.path.join(self._package_dest_dir, self.package_file)
        self.logger.info('[%s@%s] 正在下载安装包到: %s', self.name, self.ssh.host, target)
        self.logger.info('[%s@%s] 下载地址: %s', self.name, self.ssh.host, self.package_url)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self._package_dest_dir)))
        cmd = 'curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
            shlex.quote(target), self.package_url)
        code, out, err = self.ssh.execute(cmd)
        if code != 0:
            raise RuntimeError('[{}@{}] 下载安装包失败: {}，错误: {}'.format(
                self.name, self.ssh.host, self.package_file, err.strip()[:200]))
        self._pkg_path = target
        self.logger.info('[%s@%s] 安装包下载完成: %s', self.name, self.ssh.host, target)

    @staticmethod
    def _archive_ext(archive_name):
        """从归档文件名中检测格式，返回 (解压命令模板, 去除扩展名后的 basename)"""
        name = archive_name.lower()
        if name.endswith('.zip'):
            return 'unzip -o {pkg} -d {dir}', archive_name[:-4]
        if name.endswith('.tar.gz') or name.endswith('.tgz'):
            return 'tar -xzf {pkg} -C {dir}', re.sub(r'\.(tar\.gz|tgz)$', '', archive_name, flags=re.I)
        if name.endswith('.tar.xz'):
            return 'tar -xJf {pkg} -C {dir}', archive_name[:-7]
        if name.endswith('.tar.bz2') or name.endswith('.tbz2'):
            return 'tar -xjf {pkg} -C {dir}', archive_name[:-8] if name.endswith('.tar.bz2') else archive_name[:-5]
        # 兜底：让 tar 自动检测
        return 'tar -xf {pkg} -C {dir}', re.sub(r'\.(tar(\.(gz|xz|bz2))?|tgz)$', '', archive_name, flags=re.I)

    def extract_package(self):
        """解压安装包到目标目录，创建版本化软链接

        幂等性：如果组件目录已存在，跳过解压。但会清理残留的软链接（如
        --debug dry-run 创建的、解压目录名与实际不符的软链接），避免干扰。
        """
        self.logger.info('[%s@%s] 正在解压安装包: %s', self.name, self.ssh.host, self.package_file)
        dest_q = shlex.quote(self._package_dest_dir)
        self.ssh.execute('mkdir -p {}'.format(dest_q))

        # 清理残留软链接：dry-run 可能创建了文件名推导 ≠ 实际解压目录名的软链接
        self.ssh.execute('rm -f {}'.format(shlex.quote(self.component_dir)))

        # 幂等检查：组件真实目录已存在则跳过解压
        code, _, _ = self.ssh.execute('test -d {}'.format(shlex.quote(self.component_dir)))
        if code == 0:
            self.logger.info('[%s@%s] %s 已存在，跳过解压',
                              self.name, self.ssh.host, self.component_dir)
            return

        extract_cmd_tpl, extracted_basename = self._archive_ext(self.package_file)

        # 调试模式：跳过实际解压，从包名推导目录名
        if self.ssh.dry_run:
            extracted_path = posixpath.join(self._package_dest_dir, extracted_basename)
            self._extracted_basename = extracted_basename
            self._extracted_path = extracted_path
            self._java_home = extracted_path
            self.logger.info('[%s@%s] (调试模式) 模拟解压到: %s',
                              self.name, self.ssh.host, extracted_path)
            symlink = self.component_dir
            if extracted_basename != self.name:
                self.ssh.execute('ln -snf {} {}'.format(
                    shlex.quote(extracted_basename), shlex.quote(symlink)))
                self.logger.info('[%s@%s] (调试模式) 模拟创建软链接: %s -> %s',
                                  self.name, self.ssh.host, symlink, extracted_basename)
            return

        # 记录解压前的目录列表
        code, before, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(dest_q)
        )
        before_set = set(before.strip().split('\n')) if before.strip() else set()

        # 按归档格式执行解压（大包如 MySQL 可能耗时较长，超时设为 15 分钟）
        pkg_q = shlex.quote(self._pkg_path)
        cmd = extract_cmd_tpl.format(pkg=pkg_q, dir=dest_q)
        code, out, err = self.ssh.execute(cmd, timeout=900)
        if code != 0:
            if self.package_file.endswith('.zip'):
                raise RuntimeError('[{}@{}] 解压失败: {}'.format(self.name, self.ssh.host, err))
            cmd = 'tar -xzf {} -C {}'.format(pkg_q, dest_q)
            code, out, err = self.ssh.execute(cmd, timeout=900)
        if code != 0:
            cmd = 'tar -xJf {} -C {}'.format(pkg_q, dest_q)
            code, out, err = self.ssh.execute(cmd, timeout=900)
        if code != 0:
            raise RuntimeError('[{}@{}] 解压失败: {}'.format(self.name, self.ssh.host, err))

        # 对比解压前后的目录列表，找出新增的目录
        code, after, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(dest_q)
        )
        after_set = set(after.strip().split('\n')) if after.strip() else set()
        new_entries = after_set - before_set
        new_dirs = [e for e in new_entries if e]
        if not new_dirs:
            raise RuntimeError('[{}@{}] 解压后未发现新目录'.format(self.name, self.ssh.host))

        extracted_basename = sorted(new_dirs)[0].rstrip('/')
        extracted_path = posixpath.join(self._package_dest_dir, extracted_basename)
        self._extracted_basename = extracted_basename
        self._extracted_path = extracted_path

        rename_result = self._extract_version_rename(extracted_basename, extracted_path)
        if rename_result is not None:
            extracted_basename, extracted_path = rename_result
            self._extracted_basename = extracted_basename
            self._extracted_path = extracted_path

        symlink = self.component_dir
        if extracted_basename == self.name:
            self.logger.info('[%s@%s] 跳过软链接创建（目录名与组件名一致）',
                              self.name, self.ssh.host)
        else:
            self.ssh.execute('ln -snf {} {}'.format(
                shlex.quote(extracted_basename), shlex.quote(symlink)))
            self.logger.info('[%s@%s] 软链接: %s -> %s',
                              self.name, self.ssh.host, symlink, extracted_basename)

    def render_configs(self):
        """读取本地 conf/template/{name}/ 下的模板文件，替换变量后写入远程"""
        template_root = getattr(self.config, 'config_template_dir', '') or ''
        if not template_root or not os.path.isdir(template_root):
            self.logger.warning('[%s@%s] 未找到配置模板根目录: %s', self.name, self.ssh.host, template_root)
            return
        comp_template_dir = os.path.join(template_root, self.name)
        if not os.path.isdir(comp_template_dir):
            self.logger.warning('[%s@%s] 未找到配置模板: %s', self.name, self.ssh.host, comp_template_dir)
            return

        self.logger.info('[%s@%s] 渲染配置模板目录: %s', self.name, self.ssh.host, comp_template_dir)
        vars = self.template_vars()
        file_count = 0
        for root, dirs, files in os.walk(comp_template_dir):
            # 跳过隐藏目录（如 .backup、.git 等）
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fn in sorted(files):
                # 跳过隐藏文件和系统文件
                if fn.startswith('.') or fn == 'Thumbs.db':
                    continue
                file_count += 1
                local_path = os.path.join(root, fn)
                rel_path = os.path.relpath(local_path, comp_template_dir)
                remote_path = os.path.join(self.component_dir, rel_path)
                self.ssh.execute('mkdir -p $(dirname {})'.format(shlex.quote(remote_path)))

                # 先检查所有变量是否都已提供
                with open(local_path, 'r') as fh:
                    content = fh.read()
                unresolved = re.findall(r'\$\{(.*?)\}', content)
                if unresolved:
                    missing = [v for v in unresolved if v not in vars]
                    if missing:
                        self.logger.warning('[%s@%s] 模板 %s 有未提供的变量: %s',
                                            self.name, self.ssh.host, local_path, missing)

                rendered = Template(content).safe_substitute(**vars)
                unresolved_after = re.findall(r'\$\{(.*?)\}', rendered)
                if unresolved_after:
                    self.logger.warning('[%s@%s] 模板 %s 存在未替换的变量: %s',
                                        self.name, self.ssh.host, local_path, unresolved_after)
                self.logger.info('[%s@%s] 正在生成配置文件: %s', self.name, self.ssh.host, remote_path)
                # 用 base64 编码传输，避免特殊字符被 shell 转义
                encoded = base64.b64encode(rendered.encode()).decode()
                remote_q = shlex.quote(remote_path)
                cmd = "echo '{}' | base64 -d > {}".format(encoded, remote_q)
                self.ssh.execute(cmd, check=True, log_command=False)
                self.ssh.execute('chmod 644 {}'.format(remote_q))
                self._rendered_files.append((rel_path, rendered))
        self.logger.info('[%s@%s] 配置文件渲染完成，共 %d 个文件', self.name, self.ssh.host, file_count)

    @classmethod
    def get_template_vars_doc(cls):
        """返回本组件支持的模板变量文档（供文档自动生成）"""
        return {
            'install_dir': {
                'type': 'str',
                'description': '安装根目录',
                'source': 'CLI 参数 --install-dir',
                'example': '/data/service',
            },
            'comms_dir': {
                'type': 'str',
                'description': '远程软件解压/安装目录',
                'source': '自动计算（install_dir/comms）',
                'example': '/data/service/comms',
            },
            'component_dir': {
                'type': 'str',
                'description': '组件软链接路径（comms/{name}）',
                'source': '自动计算',
                'example': '/data/service/comms/redis',
            },
            'log_dir': {
                'type': 'str',
                'description': '组件日志目录',
                'source': '自动计算（component_dir/logs）',
                'example': '/data/service/comms/redis/logs',
            },
            'data_dir': {
                'type': 'str',
                'description': '组件数据目录',
                'source': '自动计算（component_dir/data）',
                'example': '/data/service/comms/redis/data',
            },
            'host_ip': {
                'type': 'str',
                'description': '部署机 IP（目标主机下载安装包用）',
                'source': 'CLI 参数 --localaddr',
                'example': '192.168.1.100',
            },
            'node_ip': {
                'type': 'str',
                'description': '当前目标主机 IP',
                'source': 'config.yaml servers 中的 host',
                'example': '192.168.1.2',
            },
            'java_home': {
                'type': 'str',
                'description': '默认 JDK 路径（JDK 8 软链接）',
                'source': '自动计算（comms_dir/java）',
                'example': '/data/service/comms/java',
            },
        }

    @classmethod
    def _app_common_template_vars_doc(cls):
        """App 类型安装器共享的 Nacos/MySQL 模板变量文档"""
        return {
            'nacos_host': {
                'type': 'str', 'description': 'Nacos 服务地址 (IP:Port)',
                'source': '从 deploy 映射推导', 'example': '192.168.1.2:8848',
            },
            'nacos_user': {
                'type': 'str', 'description': 'Nacos 登录用户名',
                'source': '固定值 nacos', 'example': 'nacos',
            },
            'nacos_password': {
                'type': 'str', 'description': 'Nacos 登录密码',
                'source': 'config.yaml nacos.password', 'example': 'nacos',
            },
            'mysql_host': {
                'type': 'str', 'description': 'MySQL 主机地址',
                'source': '从 deploy 映射推导', 'example': '192.168.1.3',
            },
            'mysql_port': {
                'type': 'str', 'description': 'MySQL 端口',
                'source': 'config.yaml mysql.port', 'example': '3306',
            },
            'mysql_user': {
                'type': 'str', 'description': 'MySQL 连接用户',
                'source': '固定值 root', 'example': 'root',
            },
            'mysql_password': {
                'type': 'str', 'description': 'MySQL 连接密码',
                'source': 'config.yaml mysql.password', 'example': 'MySQL@123',
            },
        }

    def _with_common_app_vars(self, overrides, app_vars):
        """注入 App 安装器共享的 Nacos/MySQL 模板变量默认值。"""
        overrides.setdefault('nacos_host', app_vars.get('nacos_host', '127.0.0.1:8848'))
        overrides.setdefault('nacos_user', app_vars.get('nacos_user', 'nacos'))
        overrides.setdefault('nacos_password', app_vars.get('nacos_password', '0192023A7BBD73250516F069DF18B500'))
        overrides.setdefault('mysql_host', app_vars.get('mysql_host', '127.0.0.1'))
        overrides.setdefault('mysql_port', app_vars.get('mysql_port', '3306'))
        overrides.setdefault('mysql_user', app_vars.get('mysql_user', 'root'))
        overrides.setdefault('mysql_password', app_vars.get('mysql_password', 'MySQL@123'))
        overrides.setdefault('node_ip', self.ssh.host)
        return overrides

    def start_service(self):
        """启动服务（子类实现）"""
        pass

    def health_check(self):
        """服务健康检查（子类覆盖），默认跳过"""
        self.logger.info('[%s@%s] 服务无需健康检查', self.name, self.ssh.host)

    def create_symlink(self, target, link_name):
        """在远程主机上创建软链接"""
        self.ssh.execute('mkdir -p $(dirname {})'.format(shlex.quote(link_name)))
        self.ssh.execute('ln -snf {} {}'.format(shlex.quote(target), shlex.quote(link_name)))

    def _get_port_from_template(self, template_relpath, patterns, default=None):
        """从本地配置模板文件中提取端口号（委托 utils.template）"""
        template_dir = getattr(self.config, 'config_template_dir', '') or ''
        if not template_dir:
            return default
        return config_utils.get_port_from_template(template_dir, template_relpath, patterns, default)

    def wait_for_port(self, host, port, timeout=60, interval=2):
        """等待远程主机指定 TCP 端口开始监听"""
        self.logger.info('[%s@%s] 等待 %s:%d 端口就绪...', self.name, self.ssh.host, host, port)
        for _ in range(timeout // interval):
            code, _, _ = self.ssh.execute(
                'bash -c "cat < /dev/null > /dev/tcp/{h}/{p}" 2>/dev/null'.format(h=host, p=port)
            )
            if code == 0:
                self.logger.info('[%s@%s] %s:%d 已就绪', self.name, self.ssh.host, host, port)
                return True
            self.ssh.execute('sleep {}'.format(interval))
        self.logger.warning('[%s@%s] %s:%d 等待超时（%d秒）', self.name, self.ssh.host, host, port, timeout)
        return False

    def write_remote_file(self, remote_path, content):
        """通过 base64 编码向远程主机写入文件"""
        self.logger.info('[%s@%s] 正在写入远程文件: %s', self.name, self.ssh.host, remote_path)
        encoded = base64.b64encode(content.encode()).decode()
        remote_q = shlex.quote(remote_path)
        cmd = "echo '{}' | base64 -d > {}".format(encoded, remote_q)
        self.ssh.execute(cmd, check=True, log_command=False)
        self.ssh.execute('chmod 644 {}'.format(remote_q))
        self.logger.info('[%s@%s] 远程文件已写入: %s', self.name, self.ssh.host, remote_path)

    def _init_app_database(self, mysql_vars, db_names):
        """初始化应用数据库。mysql_vars 应包含 host/port/user/password 键。
        db_names 可以是单个数据库名或数据库名列表。"""
        from core.mysql_db import init_database
        mysql_host = mysql_vars.get('mysql_host', '127.0.0.1')
        mysql_port = mysql_vars.get('mysql_port', '3306')
        mysql_user = mysql_vars.get('mysql_user', 'root')
        mysql_password = mysql_vars.get('mysql_password', 'MySQL@123')
        if isinstance(db_names, str):
            db_names = [db_names]
        for db_name in db_names:
            self.logger.info('[%s@%s] 创建数据库: %s', self.name, self.ssh.host, db_name)
            init_database(
                self.ssh, self.install_dir,
                mysql_host, mysql_port, mysql_user, mysql_password,
                db_name, sql_file=None, logger=self.logger)

    # ── systemd 管理 ─────────────────────────────────────────────

    def _sudo_mode(self):
        """返回当前主机的 sudo 能力：root / sudo / none"""
        return getattr(self.ctx, 'sudo_mode', {}).get(self.ssh.host, 'none')

    @property
    def _use_systemd(self):
        """是否使用 systemd 管理（root 或免密 sudo 时）"""
        return self._sudo_mode() in ('root', 'sudo')

    def _archive_systemd_unit(self, unit_name, unit_content):
        """将 unit 文件归档到 {install_dir}/systemd/（供将来有 root 权限时启用）"""
        archive_dir = os.path.join(self.install_dir, 'systemd')
        remote_path = os.path.join(archive_dir, '{}.service'.format(unit_name))
        self.logger.info('[%s@%s] 归档 systemd unit: %s',
                         self.name, self.ssh.host, remote_path)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(archive_dir)))
        encoded = base64.b64encode(unit_content.encode()).decode()
        self.ssh.execute(
            "echo '{enc}' | base64 -d > {path}".format(
                enc=encoded, path=shlex.quote(remote_path)),
            check=True, log_command=False)
        self.ssh.execute('chmod 644 {}'.format(shlex.quote(remote_path)))

    def _script_start(self, cmd):
        """无 sudo 时脚本直启（nohup 后台，日志由组件脚本自管）"""
        self.logger.info('[%s@%s] 脚本直启: %s', self.name, self.ssh.host, cmd)
        self.ssh.execute(cmd, timeout=30)

    def _create_systemd_unit(self, unit_name, unit_content):
        """创建 systemd unit 文件。

        先归档到 {install_dir}/systemd/（供将来有 root 权限时启用）；有 root/免密 sudo 时
        再写入 /etc/systemd/system/。unit 中的 User=root 统一替换为当前 SSH 部署用户。

        Args:
            unit_name: service 文件名（不含 .service 后缀）
            unit_content: 完整的 unit 文件内容
        """
        service_user = getattr(self.ssh, 'username', None) or 'root'
        unit_content = unit_content.replace('User=root', 'User={}'.format(service_user))

        # 1. 始终归档（与是否立即启用解耦）
        self._archive_systemd_unit(unit_name, unit_content)

        # 2. 有 root/免密 sudo 才部署到 /etc/systemd/system/
        if not self._use_systemd:
            self.logger.info('[%s@%s] 无 sudo 权限，仅归档 unit（未写入 /etc/systemd/system/）',
                             self.name, self.ssh.host)
            return

        remote_path = '/etc/systemd/system/{}.service'.format(unit_name)
        self.logger.info('[%s@%s] 创建 systemd unit: %s (User=%s)',
                         self.name, self.ssh.host, remote_path, service_user)
        encoded = base64.b64encode(unit_content.encode()).decode()
        self.ssh.execute(
            "echo '{enc}' | base64 -d | sudo tee {path} > /dev/null".format(
                enc=encoded, path=shlex.quote(remote_path)),
            check=True, log_command=False)
        self.ssh.execute('sudo chmod 644 {}'.format(shlex.quote(remote_path)))

    def _enable_systemd_unit(self, unit_name, start=False):
        """在远程主机上启用（并可选启动）systemd unit（需 root/免密 sudo）

        Args:
            unit_name: service 名称（不含 .service 后缀）
            start: 是否立即启动服务
        """
        if not self._use_systemd:
            self.logger.info('[%s@%s] 无 sudo 权限，跳过 systemctl enable%s',
                             self.name, self.ssh.host, '/start' if start else '')
            return
        self.logger.info('[%s@%s] 启用 systemd unit: %s',
                         self.name, self.ssh.host, unit_name)
        self.ssh.execute('sudo systemctl daemon-reload')
        self.ssh.execute('sudo systemctl enable {}'.format(unit_name))
        if start:
            self.logger.info('[%s@%s] 启动服务: %s',
                             self.name, self.ssh.host, unit_name)
            self.ssh.execute('sudo systemctl start {}'.format(unit_name))

    def _disable_systemd_unit(self, unit_name, stop=False):
        """在远程主机上禁用（并可选停止）systemd unit（需 root/免密 sudo）"""
        if not self._use_systemd:
            return
        if stop:
            self.ssh.execute('sudo systemctl stop {} 2>/dev/null || true'.format(unit_name))
        self.ssh.execute('sudo systemctl disable {} 2>/dev/null || true'.format(unit_name))

    def _cleanup_package(self):
        """删除已下载到远程主机的安装包文件（健康检查通过后执行）"""
        pkg_path = getattr(self, '_pkg_path', None)
        if not pkg_path:
            return
        if self.ssh.dry_run:
            self.logger.info('[%s@%s] (调试模式) 跳过清理安装包: %s',
                             self.name, self.ssh.host, pkg_path)
        else:
            self.logger.info('[%s@%s] 清理安装包: %s', self.name, self.ssh.host, pkg_path)
            self.ssh.execute('rm -f {}'.format(shlex.quote(pkg_path)))
