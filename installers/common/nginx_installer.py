# -*- coding: utf-8 -*-
"""
Nginx 安装器 — 编译安装
上传 nginx 源码包及编译依赖（zlib / pcre / openssl），解压后编译安装到版本化目录，创建软链接并启动
"""
import os
import shlex
import shutil

from installers.common.base_installer import BaseInstaller
from utils.health import NginxChecker
from core.config_utils import get_component_config


class NginxInstaller(BaseInstaller):
    GROUP = 'common'

    @classmethod
    def get_template_vars_doc(cls):
        base = super(NginxInstaller, cls).get_template_vars_doc()
        base.update({
            'odc_ip': {
                'type': 'str',
                'description': 'ODC 服务 IP',
                'source': '从 deploy 中查找含 odc 的主机',
            },
            'aimeter_ip': {
                'type': 'str',
                'description': 'aimeter 服务 IP',
                'source': '从 deploy 中查找含 aimeter 的主机',
            },
            'refiner_ip': {
                'type': 'str',
                'description': 'refiner 服务 IP',
                'source': '从 deploy 中查找含 refiner 的主机',
            },
            'sso_ip': {
                'type': 'str',
                'description': '认证服务 IP',
                'source': '从 deploy 中查找含 sso 的主机',
            },
            'frontend_dir': {
                'type': 'str',
                'description': '前端静态文件目录',
                'source': '自动计算',
                'example': '/data/service/apps/odc/app_frontend/dist',
            },
            'local_ip': {
                'type': 'str',
                'description': '当前主机 IP',
                'source': 'config.servers 中的主机地址',
            },
            'nginx_listen_port': {
                'type': 'str',
                'description': 'Nginx 监听端口',
                'source': 'config.yaml nginx.listen_port',
                'example': '10082',
            },
            'nginx_user': {
                'type': 'str',
                'description': 'Nginx worker 进程运行用户',
                'source': 'servers 中的部署用户（username）',
                'example': 'eoi',
            },
        })
        return base

    # 编译依赖：(归档文件名, 解压后目录名)
    _DEPS = [
        ('zlib-1.3.1.tar.gz',   'zlib-1.3.1'),
        ('pcre-8.41.tar.gz',    'pcre-8.41'),
        ('openssl-1.1.1g.tar.gz', 'openssl-1.1.1g'),
    ]

    @property
    def _lib_dir(self):
        """本地 lib/nginx 依赖包目录"""
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(script_dir, 'lib', 'nginx')

    def _stage_dep_packages(self):
        """将依赖包从 lib/nginx/ 复制到 HTTP 服务的包目录，供远程主机下载"""
        pkg_dir = getattr(self.config, 'package_dir', '') or ''
        if not pkg_dir or not os.path.isdir(pkg_dir):
            self.logger.warning('[%s] package_dir 不可用，跳过依赖包暂存', self.name)
            return
        if not os.path.isdir(self._lib_dir):
            self.logger.warning('[%s] lib/nginx/ 目录不存在: %s', self.name, self._lib_dir)
            return

        for archive_name, _ in self._DEPS:
            dst = os.path.join(pkg_dir, archive_name)
            if os.path.exists(dst):
                continue

            # 在 lib/nginx/ 中模糊查找（处理 macOS " 2" 重名文件）
            src = os.path.join(self._lib_dir, archive_name)
            if not os.path.exists(src):
                candidates = [f for f in os.listdir(self._lib_dir)
                              if f.startswith(os.path.splitext(archive_name)[0])
                              and f.lower().endswith('.tar.gz')]
                if candidates:
                    src = os.path.join(self._lib_dir, sorted(candidates)[0])
            if os.path.exists(src):
                shutil.copy2(src, dst)
                self.logger.info('[%s] 暂存依赖包: %s -> %s', self.name, src, dst)

    def extract_package(self):
        """编译安装 nginx：解压源码 → 下载并解压依赖 → configure → make → make install → 软链接"""
        # 先确保依赖包已在 HTTP 服务目录中
        self._stage_dep_packages()

        # 1. 基类解压 nginx 源码
        super().extract_package()
        install_version = self._extracted_basename

        symlink = self.component_dir

        # 2. 重命名源码目录为 nginx-{version}-s
        src_name = install_version + '-s'
        old_path = self._extracted_path
        src_path = os.path.join(self.comms_dir, src_name)
        self.logger.info('[%s@%s] 重命名源码目录 %s -> %s',
                         self.name, self.ssh.host, self._extracted_basename, src_name)
        self.ssh.execute('mv {} {}'.format(
            shlex.quote(old_path), shlex.quote(src_path)))

        # 3. 下载并解压依赖包到 comms/ 目录
        host_ip = self.config.host_ip
        http_port = self.config.http_port
        for archive_name, extract_dir in self._DEPS:
            dep_url = 'http://{}:{}/{}'.format(host_ip, http_port, archive_name)
            dep_path = os.path.join(self.comms_dir, archive_name)
            self.logger.info('[%s@%s] 下载依赖: %s', self.name, self.ssh.host, archive_name)
            self.ssh.execute('curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
                shlex.quote(dep_path), dep_url))
            self.logger.info('[%s@%s] 解压依赖: %s', self.name, self.ssh.host, archive_name)
            self.ssh.execute('tar -xzf {} -C {}'.format(
                shlex.quote(dep_path), shlex.quote(self.comms_dir)))
            self.ssh.execute('rm -f {}'.format(shlex.quote(dep_path)))

        # 4. 编译安装
        install_prefix = os.path.join(self.comms_dir, install_version)
        src_q = shlex.quote(src_path)
        prefix_q = shlex.quote(install_prefix)

        configure_cmd = (
            'cd {} && ./configure'
            ' --prefix={}'
            ' --with-http_stub_status_module'
            ' --with-zlib=../zlib-1.3.1'
            ' --with-pcre=../pcre-8.41'
            ' --with-openssl=../openssl-1.1.1g'
        ).format(src_q, prefix_q)

        self.logger.info('[%s@%s] 配置 nginx', self.name, self.ssh.host)
        self.ssh.execute(configure_cmd, timeout=120)

        self.logger.info('[%s@%s] 编译 nginx', self.name, self.ssh.host)
        self.ssh.execute('cd {} && make'.format(src_q), timeout=600)

        self.logger.info('[%s@%s] 安装 nginx 到 %s',
                         self.name, self.ssh.host, install_prefix)
        self.ssh.execute('cd {} && make install'.format(src_q), timeout=120)

        # 5. 清理编译依赖（逐目录删除，禁止使用通配符）
        for archive_name, extract_dir in self._DEPS:
            dep_path = os.path.join(self.comms_dir, extract_dir)
            self.logger.info('[%s@%s] 清理编译依赖: %s',
                             self.name, self.ssh.host, dep_path)
            self.ssh.execute('rm -rf {}'.format(shlex.quote(dep_path)))

        # 6. 创建软链接 comms/nginx -> nginx-{version}
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(install_version), shlex.quote(symlink)))
        self.logger.info('[%s@%s] 软链接: %s -> %s',
                         self.name, self.ssh.host, symlink, install_version)

        self._extracted_basename = install_version
        self._extracted_path = install_prefix

    def _get_service_ip(self, service_name):
        """从 comp_hosts 中查找服务所在主机的 IP

        comp_hosts 是 deploy 的反向映射（组件 -> 主机列表）。
        如果未找到，返回 nginx 安装主机的 IP。
        """
        hosts = getattr(self.ctx, 'comp_hosts', {}).get(service_name, [])
        if hosts:
            return hosts[0]
        return self.ssh.host

    def template_vars(self, **overrides):
        """添加 nginx 专属变量"""
        vars = super().template_vars(**overrides)
        vars['odc_ip'] = self._get_service_ip('odc')
        vars['aimeter_ip'] = self._get_service_ip('aimeter')
        vars['refiner_ip'] = self._get_service_ip('refiner')
        vars['sso_ip'] = self._get_service_ip('sso')
        vars['frontend_dir'] = os.path.join(self.install_dir, 'apps/odc/app_frontend/dist')
        vars['local_ip'] = self.ssh.host
        nginx_cfg = get_component_config(self.config, 'nginx')
        vars['nginx_listen_port'] = str(nginx_cfg.get('listen_port', 10082))
        vars['nginx_user'] = getattr(self.ssh, 'username', None) or 'root'
        return vars

    def _create_data_dirs(self):
        """创建 nginx 需要的日志和临时目录"""
        super()._create_data_dirs()
        for subdir in ['client_body_temp', 'proxy_temp', 'fastcgi_temp', 'uwsgi_temp', 'scgi_temp']:
            path = os.path.join(self.component_dir, subdir)
            self.ssh.execute('mkdir -p {}'.format(shlex.quote(path)))

    def start_service(self):
        """启动 nginx（-p 覆盖编译时 prefix，-c 指定配置路径）"""
        self.logger.info('[%s@%s] 启动 nginx', self.name, self.ssh.host)
        cd = shlex.quote(self.component_dir)
        unit = '''[Unit]
Description=Nginx
After=network.target

[Service]
Type=forking
ExecStartPre={cd}/sbin/nginx -p {cd} -t -c {cd}/conf/nginx.conf
ExecStart={cd}/sbin/nginx -p {cd} -c {cd}/conf/nginx.conf
ExecReload={cd}/sbin/nginx -p {cd} -c {cd}/conf/nginx.conf -s reload
ExecStop={cd}/sbin/nginx -p {cd} -c {cd}/conf/nginx.conf -s quit
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(cd=cd)
        self._create_systemd_unit('nginx', unit)
        if self._use_systemd:
            self._enable_systemd_unit('nginx', start=True)
        else:
            self._script_start('{}/sbin/nginx -p {} -t -c {}/conf/nginx.conf'.format(cd, cd, cd))
            self._script_start('{}/sbin/nginx -p {} -c {}/conf/nginx.conf'.format(cd, cd, cd))

    def health_check(self):
        checker = NginxChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
        self.logger.info('[%s@%s] nginx 健康检查通过', self.name, self.ssh.host)
