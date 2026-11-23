# -*- coding: utf-8 -*-
"""
MySQL 安装器 — 单机部署
创建 mysql 系统用户，初始化数据目录，设置 root 密码并开启远程访问
"""
import base64
import os
import shlex
from string import Template

from core.mysql_db import distribute_mysql_client
from core.ssh_client import get_ssh_client
from core.config_utils import get_mysql_port
from installers.common.base_installer import BaseInstaller
from utils.health import MySQLChecker


class MySQLInstaller(BaseInstaller):
    GROUP = 'common'

    @classmethod
    def get_template_vars_doc(cls):
        base = super(MySQLInstaller, cls).get_template_vars_doc()
        base.update({
            'mysql_data_dir': {
                'type': 'str',
                'description': 'MySQL 数据目录',
                'source': 'config.yaml mysql.data_dir，默认组件 data 目录',
                'example': '/data/mysql/data',
            },
            'mysql_log_dir': {
                'type': 'str',
                'description': 'MySQL 错误日志目录',
                'source': 'config.yaml mysql.log_dir，默认组件 logs 目录',
                'example': '/data/service/comms/mysql/logs',
            },
            'mysql_pid_dir': {
                'type': 'str',
                'description': 'MySQL pid 文件目录',
                'source': 'config.yaml mysql.pid_dir，默认同日志目录',
                'example': '/data/service/comms/mysql/logs',
            },
            'mysql_run_user': {
                'type': 'str',
                'description': 'mysqld 运行用户',
                'source': '有 sudo 时固定为 mysql，无 sudo 时为部署用户',
                'example': 'mysql',
            },
        })
        return base

    @property
    def _mysql_client_components(self):
        """读取需要 MySQL 客户端的组件列表，默认只包含 nacos"""
        cfg = getattr(self.config, 'raw_config', {}) or {}
        return set(cfg.get('mysql', {}).get('client_components', ['nacos']))

    def template_vars(self, **overrides):
        overrides.setdefault('mysql_port', str(get_mysql_port(self.config)))
        overrides.setdefault('mysql_data_dir', self._mysql_data_dir)
        overrides.setdefault('mysql_log_dir', self._mysql_log_dir)
        overrides.setdefault('mysql_pid_dir', self._mysql_pid_dir)
        # my.cnf 的 user：有 sudo 用 mysql 系统用户，无 sudo 用部署用户
        overrides.setdefault('mysql_run_user',
                             'mysql' if self._use_systemd else (getattr(self.ssh, 'username', None) or 'root'))
        return super().template_vars(**overrides)

    @property
    def _mysql_data_dir(self):
        """MySQL 数据目录，config.yaml mysql.data_dir 可覆盖，默认组件 data 目录"""
        cfg = getattr(self.config, 'raw_config', {}) or {}
        return cfg.get('mysql', {}).get('data_dir', self.data_dir)

    @property
    def _mysql_log_dir(self):
        """MySQL 错误日志目录，config.yaml mysql.log_dir 可覆盖，默认组件 logs 目录"""
        cfg = getattr(self.config, 'raw_config', {}) or {}
        return cfg.get('mysql', {}).get('log_dir', self.log_dir)

    @property
    def _mysql_pid_dir(self):
        """MySQL pid 文件目录，config.yaml mysql.pid_dir 可覆盖，默认同日志目录"""
        cfg = getattr(self.config, 'raw_config', {}) or {}
        return cfg.get('mysql', {}).get('pid_dir', self._mysql_log_dir)

    def _create_dirs(self):
        super()._create_dirs()
        # 创建 mysql 系统用户（不存在时才创建）；无 sudo 时跳过（以部署用户运行）
        if not self._use_systemd:
            return
        self.ssh.execute(
            'id mysql 2>/dev/null || '
            'sudo useradd -r -d /nonexistent -s /sbin/nologin mysql 2>&1; true'
        )

    def _create_data_dirs(self):
        # data/log 目录需可写：有 sudo 时 chown 给 mysql 用户，无 sudo 时属主为部署用户
        self.logger.info('[%s@%s] 创建数据/日志目录: %s, %s',
                          self.name, self.ssh.host, self._mysql_data_dir, self.log_dir)
        dirs = [self._mysql_data_dir, self.log_dir, self._mysql_log_dir, self._mysql_pid_dir]
        for d in dict.fromkeys(dirs):
            if self._use_systemd:
                self.ssh.execute('sudo mkdir -p {}'.format(shlex.quote(d)))
                self.ssh.execute('sudo chown -R mysql:mysql {}'.format(shlex.quote(d)))
            else:
                self.ssh.execute('mkdir -p {}'.format(shlex.quote(d)))

        # 自定义数据目录（如 /data/mysql/data）时的上级目录处理（仅 systemd 模式）：
        # 父目录（如 /data/mysql）归属 mysql 用户，顶层目录（如 /data）开放 777，
        # 确保 mysql 用户能穿越 sudo mkdir -p 创建的 root 属主中间目录
        if not self._use_systemd:
            return
        data_dir = self._mysql_data_dir
        if data_dir != self.data_dir:
            parent = os.path.dirname(data_dir.rstrip('/'))
            if parent and parent != '/':
                self.ssh.execute('sudo chown -R mysql:mysql {}'.format(shlex.quote(parent)))
            top = os.path.dirname(parent)
            if top and top != '/':
                self.ssh.execute('sudo chmod 777 {}'.format(shlex.quote(top)))

    def _deploy_mycnf(self):
        """渲染 my.cnf 并部署到 /etc/，自动备份已有配置"""
        template_dir = getattr(self.config, 'config_template_dir', '') or ''
        if not template_dir:
            return
        local_path = os.path.join(template_dir, 'mysql', 'my.cnf')
        if not os.path.isfile(local_path):
            self.logger.warning(
                '[%s@%s] 未找到 my.cnf 模板: %s', self.name, self.ssh.host, local_path
            )
            return

        # 读取模板并渲染
        with open(local_path, 'r') as f:
            content = f.read()
        rendered = Template(content).safe_substitute(**self.template_vars())

        if not self._use_systemd:
            # 无 sudo：写组件目录 my.cnf，mysqld 通过 --defaults-file 指向它
            comp_mycnf = os.path.join(self.component_dir, 'my.cnf')
            self.logger.info('[%s@%s] 部署 my.cnf 到组件目录: %s',
                             self.name, self.ssh.host, comp_mycnf)
            encoded = base64.b64encode(rendered.encode()).decode()
            self.ssh.execute(
                "echo '{enc}' | base64 -d > {path}".format(
                    enc=encoded, path=shlex.quote(comp_mycnf)),
                check=True, log_command=False)
            self.ssh.execute('chmod 644 {}'.format(shlex.quote(comp_mycnf)))
            return

        # 有 sudo：写 /etc/my.cnf
        # 备份已有 /etc/my.cnf（带时间戳）
        self.logger.info('[%s@%s] 备份 /etc/my.cnf（如存在）', self.name, self.ssh.host)
        self.ssh.execute(
            'if [ -f /etc/my.cnf ]; then '
            'sudo cp /etc/my.cnf /etc/my.cnf.bak.$(date +%Y%m%d%H%M%S); '
            'fi'
        )

        # 写入 /etc/my.cnf（sudo tee 绕过 shell 重定向的权限问题）
        self.logger.info('[%s@%s] 部署 /etc/my.cnf', self.name, self.ssh.host)
        encoded = base64.b64encode(rendered.encode()).decode()
        self.ssh.execute(
            "echo '{}' | base64 -d | sudo tee /etc/my.cnf > /dev/null".format(encoded),
            check=True, log_command=False
        )
        self.ssh.execute('sudo chmod 644 /etc/my.cnf')
        self.ssh.execute('sudo chown mysql:mysql /etc/my.cnf')

        # 清理 component_dir 下的 my.cnf（避免与 /etc/ 冲突）
        comp_mycnf = os.path.join(self.component_dir, 'my.cnf')
        self.ssh.execute('rm -f {}'.format(shlex.quote(comp_mycnf)))

    def start_service(self):
        # 部署 my.cnf（有 sudo 写 /etc，无 sudo 写组件目录）
        self._deploy_mycnf()

        service_user = getattr(self.ssh, 'username', None) or 'root'

        if not self._use_systemd:
            # ── 无 sudo：以部署用户运行 ──
            DIR = self.component_dir
            # 初始化数据目录（不 sudo，省略 --user，以部署用户身份）
            self.logger.info('[%s@%s] 初始化 MySQL 数据目录（部署用户）',
                             self.name, self.ssh.host)
            self.ssh.execute(
                '{dir}/bin/mysqld --initialize-insecure --basedir={dir} --datadir={data} 2>&1'
                .format(dir=DIR, data=self._mysql_data_dir))

            # 归档 systemd unit（User=部署用户，供将来有 root 权限时启用）
            unit = '''[Unit]
Description=MySQL Server
After=network.target

[Service]
Type=simple
User={user}
ExecStart={dir}/bin/mysqld --defaults-file={dir}/my.cnf
Restart=on-failure

[Install]
WantedBy=multi-user.target'''.format(user=service_user, dir=DIR)
            self._archive_systemd_unit('mysqld', unit)

            # 脚本直启
            self.logger.info('[%s@%s] 脚本直启 MySQL', self.name, self.ssh.host)
            self._script_start(
                'nohup {dir}/bin/mysqld --defaults-file={dir}/my.cnf > /dev/null 2>&1 &'
                .format(dir=DIR))
        else:
            # ── 有 sudo：保持现状（mysql 系统用户）──
            # 将 comms 目录下的实际版本目录和软链接改为 mysql:mysql 属主
            DIR = shlex.quote(self.component_dir)
            self.ssh.execute(
                'sudo chown -R mysql:mysql $(readlink -f {d}) 2>/dev/null; '
                'sudo chown -h mysql:mysql {d} 2>/dev/null'.format(d=DIR))

            # 初始化数据目录（sudo 执行：--user=mysql 要求 root 权限切换用户，非 root 部署用户必需）
            self.logger.info('[%s@%s] 初始化 MySQL 数据目录', self.name, self.ssh.host)
            self.ssh.execute(
                'sudo {dir}/bin/mysqld --initialize-insecure --basedir={dir} --datadir={data} --user=mysql 2>&1'
                .format(dir=self.component_dir, data=self._mysql_data_dir)
            )

            # 注册为系统服务（systemd unit，CentOS 7 / EL8 / EL9 通用）
            # 注意：mysqld 直接执行时是前台进程（不 fork 退出），必须用 Type=simple；
            # 用 Type=forking 会导致 systemd 等待 ExecStart 退出超时（90s）后误杀 mysqld，
            # 配合 Restart=on-failure 形成"启动→超时→误杀→重启"死循环
            DIR = self.component_dir
            unit = '''[Unit]
Description=MySQL Server
After=network.target

[Service]
Type=simple
User=mysql
Group=mysql
ExecStart={dir}/bin/mysqld --defaults-file=/etc/my.cnf
Restart=on-failure

[Install]
WantedBy=multi-user.target
'''.format(dir=DIR)
            self.logger.info('[%s@%s] 注册 MySQL 系统服务（systemd）', self.name, self.ssh.host)
            encoded = base64.b64encode(unit.encode()).decode()
            self.ssh.execute(
                "echo '{enc}' | base64 -d | sudo tee /etc/systemd/system/mysqld.service > /dev/null"
                .format(enc=encoded),
                check=True, log_command=False
            )
            self.ssh.execute('sudo chmod 644 /etc/systemd/system/mysqld.service')
            self.ssh.execute('sudo systemctl daemon-reload')

            # 启动 MySQL（需 sudo 操作 systemd）
            self.logger.info('[%s@%s] 启动 MySQL', self.name, self.ssh.host)
            self.ssh.execute('sudo systemctl enable mysqld')
            self.ssh.execute('sudo systemctl start mysqld')

        # 等待 MySQL 就绪（轮询 30 次，每次 2 秒）
        self.logger.info('[%s@%s] 等待 MySQL 启动...', self.name, self.ssh.host)
        self.ssh.execute(
            'for i in $(seq 1 30); do '
            '  {dir}/bin/mysqladmin ping --silent 2>/dev/null && break; '
            '  sleep 2; '
            'done'
            .format(dir=self.component_dir)
        )

        # 设置 root 密码
        BIN = self.component_dir + '/bin/mysql'
        ROOT = 'root'
        PWD = getattr(self.config, 'mysql_password', 'MySQL@123')

        self.logger.info('[%s@%s] 设置 root 密码', self.name, self.ssh.host)
        self.ssh.execute(
            "{b} -u {r} -e \"ALTER USER '{r}'@'localhost' IDENTIFIED BY '{p}';\" 2>&1"
            .format(b=BIN, r=ROOT, p=PWD)
        )

        # 允许远程连接
        self.logger.info('[%s@%s] 配置 root 远程访问', self.name, self.ssh.host)
        self.ssh.execute(
            "{b} -u {r} -p'{p}' -e \""
            "CREATE USER IF NOT EXISTS '{r}'@'%' IDENTIFIED BY '{p}'; "
            "GRANT ALL PRIVILEGES ON *.* TO '{r}'@'%' WITH GRANT OPTION; "
            "FLUSH PRIVILEGES;\" 2>&1"
            .format(b=BIN, r=ROOT, p=PWD)
        )

    def install(self, skip_health_check=False):
        super().install(skip_health_check=skip_health_check)
        # 只向需要执行数据库命令的组件所在主机分发 MySQL 客户端
        target_hosts = set()
        for comp in self._mysql_client_components:
            for host in getattr(self.ctx, 'comp_hosts', {}).get(comp, []):
                target_hosts.add(host)
        if target_hosts:
            servers_map = getattr(self.ctx, 'servers_map', {}) or {}
            distribute_mysql_client(
                MySQLInstaller, self.ssh, self.config, self.ctx, self.logger,
                target_hosts, servers_map, self.comms_dir, self.package_file)

    def health_check(self):
        pwd = getattr(self.config, 'mysql_password', 'MySQL@123')
        checker = MySQLChecker(self.ssh, self.component_dir, self.config, self.logger,
                               password=pwd)
        checker.check()
        self.logger.info('[%s@%s] MySQL 健康检查通过', self.name, self.ssh.host)
        self.logger.info('[%s@%s] MySQL 初始化完成，允许远程访问', self.name, self.ssh.host)
