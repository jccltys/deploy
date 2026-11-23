# -*- coding: utf-8 -*-
"""Nebula Graph 安装器 — 支持 1 台或 3 台主机部署

解压后复制 .default 配置文件，写入 meta_server_addrs 和 local_ip。
启动方式统一为 scripts/nebula.service start all。
"""
import os
import shlex
import time

from core import config_utils
from core.config_utils import get_component_config
from installers.common.base_installer import BaseInstaller
from core.ssh_client import get_ssh_client
from utils.health import NebulaChecker


class NebulaInstaller(BaseInstaller):
    GROUP = 'common'
    PACKAGE_NAME = 'nebula-graph'
    CONSOLE_BINARY = 'nebula-console-linux-amd64-v3.8.0'   # 默认值（兜底）

    @classmethod
    def post_deploy(cls, hosts, instances, servers_map, config, context, logger, results, failed):
        """Nebula 后置初始化：init_schema 是全局初始化，单机/多机都只在 first_host 初始化一次"""
        if failed:
            return
        first_host = sorted(hosts)[0]
        server_info = servers_map.get(first_host)
        if not server_info:
            return
        nebula_ssh = get_ssh_client(server_info, dry_run=config.debug, logger=logger)
        try:
            nebula_inst = cls(nebula_ssh, config, context, logger)
            nebula_inst.init_schema()
        except Exception as e:
            logger.warning('[nebula] schema 初始化异常: %s', e)
        finally:
            nebula_ssh.close()

    def _get_nebula_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('nebula', []))

    def _is_cluster(self):
        return len(self._get_nebula_hosts()) == 3

    def _get_nebula_ports(self):
        nebula_cfg = get_component_config(self.config, 'nebula')
        return {
            'metad': nebula_cfg.get('meta_port', 9559),
            'graphd': nebula_cfg.get('graphd_port', 9669),
            'storaged': nebula_cfg.get('storaged_port', 9779),
        }

    def _copy_default_configs(self):
        etc_dir = os.path.join(self.component_dir, 'etc')
        code, out, _ = self.ssh.execute(
            'ls -1 {}/*.default 2>/dev/null'.format(shlex.quote(etc_dir)))
        if code != 0 or not out.strip():
            self.logger.info(
                '[%s@%s] 未找到 .default 配置文件，跳过复制',
                self.name, self.ssh.host)
            return
        for line in out.strip().split('\n'):
            src = line.strip()
            dst = src[:-8]
            self.ssh.execute('cp {} {}'.format(
                shlex.quote(src), shlex.quote(dst)))
            self.logger.info(
                '[%s@%s] 复制配置: %s -> %s',
                self.name, self.ssh.host,
                os.path.basename(src), os.path.basename(dst))

    def _sed_config(self, conf_file, key, value):
        quoted_conf = shlex.quote(conf_file)
        full_key = '--' + key
        pattern = shlex.quote('^{}='.format(full_key))
        new_line_value = '{}={}'.format(full_key, value)
        cmd_check = 'grep -q {} {}'.format(pattern, quoted_conf)
        code, _, _ = self.ssh.execute(cmd_check)
        if code == 0:
            cmd = "sed -i 's/^{}=.*/{}/' {}".format(
                full_key, new_line_value, quoted_conf)
            self.ssh.execute(cmd)
        else:
            self.logger.warning(
                '[%s@%s] 配置项 %s 不存在于 %s，跳过修改',
                self.name, self.ssh.host, key, conf_file)

    def _modify_configs(self):
        etc_dir = os.path.join(self.component_dir, 'etc')
        nebula_vars = config_utils.get_nebula_vars(self.ctx, self.config)
        meta_addrs = nebula_vars['meta_server_addr'] if nebula_vars else None
        if not meta_addrs:
            self.logger.error(
                '[%s@%s] 无法获取 meta_server_addr，跳过配置修改',
                self.name, self.ssh.host)
            return
        local_ip = self.ssh.host

        configs = [
            'nebula-graphd.conf',
            'nebula-metad.conf',
            'nebula-storaged.conf',
        ]
        for conf_name in configs:
            conf_path = os.path.join(etc_dir, conf_name)
            code, _, _ = self.ssh.execute(
                'test -f {}'.format(shlex.quote(conf_path)))
            if code != 0:
                self.logger.warning(
                    '[%s@%s] 配置文件不存在，跳过: %s',
                    self.name, self.ssh.host, conf_path)
                continue
            self._sed_config(conf_path, 'meta_server_addrs', meta_addrs)
            self._sed_config(conf_path, 'local_ip', local_ip)
            self._sed_config(conf_path, 'ws_ip', local_ip)
            self.logger.info(
                '[%s@%s] 已修改 %s: meta_server_addrs=%s, local_ip=%s',
                self.name, self.ssh.host, conf_name, meta_addrs, local_ip)

    def _resolve_console_binary(self):
        """扫描本地包目录，按 nebula-console 前缀自动发现文件名，不匹配时用默认值。"""
        pkg_dir = getattr(self.config, 'package_dir', None)
        if pkg_dir:
            search_dir = os.path.join(pkg_dir, self.group)
            if os.path.isdir(search_dir):
                for f in sorted(os.listdir(search_dir)):
                    if f.startswith('nebula-console'):
                        return f
        return self.CONSOLE_BINARY

    def _install_console(self):
        bin_name = self._resolve_console_binary()
        bin_path = os.path.join(self.comms_dir, bin_name)
        symlink_path = os.path.join(self.comms_dir, 'nebula-console')

        code, _, _ = self.ssh.execute('test -f {}'.format(shlex.quote(bin_path)))
        if code == 0:
            self.logger.info(
                '[%s@%s] nebula-console 已存在，跳过下载',
                self.name, self.ssh.host)
        else:
            url = 'http://{}:{}/{}/{}'.format(
                self.config.host_ip, self.config.http_port,
                self.group, bin_name)
            self.logger.info('[%s@%s] 正在下载 nebula-console: %s',
                             self.name, self.ssh.host, url)
            cmd = 'curl -fsS -o {} {} --retry 3 --retry-delay 5'.format(
                shlex.quote(bin_path), url)
            code, out, err = self.ssh.execute(cmd)
            if code != 0:
                raise RuntimeError('[{}@{}] 下载 nebula-console 失败: {}'.format(
                    self.name, self.ssh.host, err.strip()[:200]))
            self.logger.info('[%s@%s] nebula-console 下载完成',
                             self.name, self.ssh.host)

        self.ssh.execute('chmod +x {}'.format(shlex.quote(bin_path)))
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(bin_name), shlex.quote(symlink_path)))
        self.logger.info('[%s@%s] nebula-console 软链接就绪: %s -> %s',
                         self.name, self.ssh.host, symlink_path, bin_path)

    def init_schema(self):
        nebula_vars = config_utils.get_nebula_vars(self.ctx, self.config)
        if not nebula_vars:
            self.logger.warning(
                '[%s@%s] 无法获取 nebula 配置，跳过 schema 初始化',
                self.name, self.ssh.host)
            return

        console = os.path.join(self.comms_dir, 'nebula-console')
        graphd_port = nebula_vars['nebula_graphd_port']
        user = nebula_vars['nebula_graphd_user']
        password = nebula_vars['nebula_graphd_password']
        space_name = nebula_vars['nebula_space_name']
        partition_num = nebula_vars['nebula_space_partition_num']
        replica_factor = nebula_vars['nebula_space_replica_factor']
        vid_type = nebula_vars['nebula_space_vid_type']
        edge_name = nebula_vars['nebula_edge_name']
        storaged_addrs = nebula_vars['storaged_server_addr']

        space_ddl = 'CREATE SPACE `{}` (partition_num={}, replica_factor={}, vid_type={})'.format(
            space_name, partition_num, replica_factor, vid_type)
        edge_ddl = "CREATE EDGE `{}` (`type` string NULL) ttl_duration = 0, ttl_col = \"\"".format(
            edge_name)

        base_cmd = '{} -addr {} -port {} -u {} -p {}'.format(
            shlex.quote(console), self.ssh.host, graphd_port,
            shlex.quote(user), shlex.quote(password))

        self.logger.info('[%s@%s] 开始 Nebula schema 初始化', self.name, self.ssh.host)

        # ADD HOSTS
        self.logger.info('[%s@%s] 执行: ADD HOSTS %s', self.name, self.ssh.host, storaged_addrs)
        self.ssh.execute('{} -e {}'.format(base_cmd, shlex.quote('ADD HOSTS ' + storaged_addrs)))

        # 等待所有 storaged 节点 ONLINE，每 1 分钟检查一次
        max_retries = 5
        all_online = False
        for attempt in range(1, max_retries + 1):
            self.logger.info('[%s@%s] 检查 SHOW HOSTS（第 %d/%d 次）',
                             self.name, self.ssh.host, attempt, max_retries)
            check_cmd = '{} -e "SHOW HOSTS" | awk -F\'|\' \'/ONLINE|OFFLINE/ {{gsub(/"/,"",$4); print $4}}\''.format(
                base_cmd)
            code, out, _ = self.ssh.execute(check_cmd)
            if code == 0:
                statuses = [s.strip() for s in out.strip().split('\n') if s.strip()]
                if 'OFFLINE' not in statuses:
                    all_online = True
                    self.logger.info(
                        '[%s@%s] 所有 storaged 节点已 ONLINE (%d)',
                        self.name, self.ssh.host, len(statuses))
                    break
                self.logger.info(
                    '[%s@%s] 存在 OFFLINE 节点，等待 60 秒...',
                    self.name, self.ssh.host)
            else:
                self.logger.info(
                    '[%s@%s] SHOW HOSTS 查询失败，等待 60 秒后重试',
                    self.name, self.ssh.host)
            if attempt < max_retries:
                time.sleep(60)

        if not all_online:
            self.logger.warning(
                '[%s@%s] storaged 节点未全部 ONLINE，跳过 schema 初始化',
                self.name, self.ssh.host)
            return

        # CREATE SPACE
        self.logger.info('[%s@%s] 执行: %s', self.name, self.ssh.host, space_ddl)
        self.ssh.execute('{} -e {}'.format(base_cmd, shlex.quote(space_ddl)))

        # 等待 space 就绪
        self.logger.info('[%s@%s] 等待 space %s 就绪...', self.name, self.ssh.host, space_name)
        self.ssh.execute('sleep 20')

        # 等待 space 就绪，每 10 秒检查一次 SHOW SPACES，最多 5 次
        space_ready = False
        for attempt in range(1, 6):
            self.logger.info('[%s@%s] 检查 SHOW SPACES（第 %d/5 次）',
                             self.name, self.ssh.host, attempt)
            code, out, _ = self.ssh.execute(
                '{} -e {}'.format(base_cmd, shlex.quote('SHOW SPACES')))
            if code == 0 and '"{}"'.format(space_name) in out:
                space_ready = True
                self.logger.info('[%s@%s] space %s 已就绪', self.name, self.ssh.host, space_name)
                break
            self.logger.info('[%s@%s] space %s 未就绪，等待 10 秒...',
                             self.name, self.ssh.host, space_name)
            if attempt < 5:
                time.sleep(10)

        if space_ready:
            # 等待 space 元数据同步完成
            self.logger.info('[%s@%s] space %s 已就绪，等待 20 秒后创建 edge',
                             self.name, self.ssh.host, space_name)
            time.sleep(20)
            # CREATE EDGE（在对应 space 中）
            use_edge_sql = 'USE {}; {}'.format(space_name, edge_ddl)
            self.logger.info('[%s@%s] 执行: %s', self.name, self.ssh.host, edge_ddl)
            self.ssh.execute('{} -e {}'.format(base_cmd, shlex.quote(use_edge_sql)))
        else:
            self.logger.warning(
                '[%s@%s] space %s 未就绪，跳过创建 edge',
                self.name, self.ssh.host, space_name)

        self.logger.info('[%s@%s] Nebula schema 初始化完成', self.name, self.ssh.host)

    def prepare(self):
        """覆盖基类 prepare，跳过模板渲染（NebulaGraph 配置来源于包内的 .default 文件，不依赖 conf/template/nebula/）
        
        将 _copy_default_configs 和 _modify_configs 放在 prepare 中而不是 install 中，
        因为多主机部署走 _deploy_multi_host() 只调用 prepare() + start_service()，
        不会调用 install()。
        """
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._create_data_dirs()
        self._cleanup_package()
        self._copy_default_configs()
        self._modify_configs()
        self._install_console()

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 ===', self.name, self.ssh.host)
        self.prepare()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self.logger.info('[%s@%s] === 安装完成 ===', self.name, self.ssh.host)

    def start_service(self):
        mode = '集群' if self._is_cluster() else '单节点'
        self.logger.info('[%s@%s] 启动 Nebula Graph（%s模式）',
                         self.name, self.ssh.host, mode)
        if self.config.debug:
            self.logger.info('调试模式：跳过 Nebula 启动')
            return
        scripts_dir = os.path.join(self.component_dir, 'scripts')
        scripts_q = shlex.quote(scripts_dir)
        unit_content = '''[Unit]
Description=Nebula Graph
After=network.target

[Service]
Type=forking
ExecStart={scripts_q}/nebula.service start all
ExecStop={scripts_q}/nebula.service stop all
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target'''.format(scripts_q=scripts_q)
        self._create_systemd_unit('nebula', unit_content)
        if self._use_systemd:
            self._enable_systemd_unit('nebula', start=True)
        else:
            self._script_start('cd {} && ./nebula.service start all'.format(scripts_q))

    def health_check(self):
        ports = self._get_nebula_ports()
        NebulaChecker(
            self.ssh, self.component_dir, self.config, self.logger,
            graphd_port=ports['graphd']
        ).check()
        self.logger.info('[%s@%s] Nebula Graph 健康检查通过',
                         self.name, self.ssh.host)
