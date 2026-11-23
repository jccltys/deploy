# -*- coding: utf-8 -*-
"""
Hadoop 安装器 — 集群模式
生成 Hadoop 全套配置（core-site / hdfs-site / mapred-site / yarn-site / hadoop-env）
通过 start-dfs.sh + start-yarn.sh 启动
"""
import base64
import os
import shlex
import time

from core.ssh_client import SSHClient
from installers.common.base_installer import BaseInstaller
from utils.health import HadoopChecker
from core.config_utils import get_zookeeper_cluster_hosts


class HadoopInstaller(BaseInstaller):
    GROUP = 'common'
    DEPLOY_MODE = 'legacy'
    REQUIRES_ZK_CHECK = True

    @classmethod
    def get_template_vars_doc(cls):
        base = super(HadoopInstaller, cls).get_template_vars_doc()
        base.update({
            'nn1_host': {
                'type': 'str',
                'description': '主 NameNode 主机名',
                'source': 'deploy 映射中第一个 hadoop 主机',
            },
            'nn2_host': {
                'type': 'str',
                'description': '备用 NameNode 主机名',
                'source': 'deploy 映射中第二个 hadoop 主机（如存在）',
            },
            'rm1_host': {
                'type': 'str',
                'description': '主 ResourceManager 主机名',
                'source': '同 nn1_host',
            },
            'rm2_host': {
                'type': 'str',
                'description': '备用 ResourceManager 主机名',
                'source': '同 nn2_host',
            },
            'rm_id': {
                'type': 'str',
                'description': '当前主机的 RM 角色 ID',
                'source': '自动分配（rm1 或 rm2）',
                'example': 'rm1',
            },
            'zk_quorum': {
                'type': 'str',
                'description': 'ZooKeeper 仲裁地址列表',
                'source': '自动从 deploy 映射推导',
                'example': 'node1:2181,node2:2181,node3:2181',
            },
            'jnode_hosts': {
                'type': 'str',
                'description': 'JournalNode 地址列表（分号分隔）',
                'source': '所有 hadoop 主机',
                'example': 'node1:8485;node2:8485;node3:8485',
            },
        })
        return base

    @property
    def _hadoop_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('hadoop', []))

    @property
    def _nn1_host(self):
        hosts = self._hadoop_hosts
        return hosts[0] if hosts else ''

    @property
    def _nn2_host(self):
        hosts = self._hadoop_hosts
        return hosts[1] if len(hosts) >= 2 else ''

    @property
    def _is_nn1(self):
        return self.ssh.host == self._nn1_host

    @property
    def _is_nn2(self):
        return self.ssh.host == self._nn2_host

    def _create_dirs(self):
        super()._create_dirs()

    def _create_data_dirs(self):
        super()._create_data_dirs()
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.data_dir + '/namenode')))
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.data_dir + '/datanode')))
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.data_dir + '/pids')))

    def _resolve_hostnames(self):
        if getattr(self.ctx, 'hostname_map', None):
            return
        hostname_map = {}
        hosts_path = '/etc/hosts'
        if os.path.isfile(hosts_path):
            with open(hosts_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            hostname_map[parts[0]] = parts[1].split('.')[0]
        self.ctx.hostname_map = hostname_map

    def template_vars(self, **overrides):
        hostname_map = getattr(self.ctx, 'hostname_map', {}) or {}
        def resolve(ip):
            return hostname_map.get(ip, ip)

        hadoop_hosts = self._hadoop_hosts
        nn1 = resolve(hadoop_hosts[0]) if hadoop_hosts else resolve(self.ssh.host)
        nn2 = resolve(hadoop_hosts[1]) if len(hadoop_hosts) >= 2 else nn1

        overrides.setdefault('nn1_host', nn1)
        overrides.setdefault('nn2_host', nn2)
        overrides.setdefault('rm1_host', nn1)
        overrides.setdefault('rm2_host', nn2)
        overrides.setdefault('rm_id', 'rm2' if len(hadoop_hosts) >= 2 and self.ssh.host == hadoop_hosts[1] else 'rm1')

        zk_hosts = get_zookeeper_cluster_hosts(getattr(self.ctx, 'comp_hosts', {}))
        zk_port = self._get_port_from_template(
            'zookeeper/conf/zoo.cfg', [r'clientPort=(\d+)'], default=2181)
        zk_quorum = ','.join('{}:{}'.format(resolve(h), zk_port) for h in zk_hosts) if zk_hosts else 'localhost:{}'.format(zk_port)
        overrides.setdefault('zk_quorum', zk_quorum)

        jn_hosts = ';'.join('{}:8485'.format(resolve(h)) for h in hadoop_hosts) if hadoop_hosts else 'localhost:8485'
        overrides.setdefault('jnode_hosts', jn_hosts)

        username = getattr(self.ssh, 'username', None) or 'root'
        if username == 'root':
            ssh_key_path = '/root/.ssh/id_rsa'
        else:
            ssh_key_path = '/home/{}/.ssh/id_rsa'.format(username)
        overrides.setdefault('ssh_key_path', ssh_key_path)

        return super().template_vars(**overrides)

    def _wait_for_remote_file(self, host, filepath, timeout=120):
        """等待远程主机上的文件出现（通过部署机 SSH 直接检查，不依赖节点间互信）"""
        for _ in range(timeout // 2):
            if host == self.ssh.host:
                code, _, _ = self.ssh.execute('test -f {}'.format(shlex.quote(filepath)))
            else:
                servers_map = getattr(self.ctx, 'servers_map', {}) or {}
                si = servers_map.get(host)
                if si:
                    remote_ssh = SSHClient(
                        host=si['host'], port=si.get('port', 22),
                        username=si.get('username', 'root'),
                        key_file=si.get('key_file'),
                        dry_run=self.ssh.dry_run, logger=self.logger
                    )
                    code, _, _ = remote_ssh.execute('test -f {}'.format(shlex.quote(filepath)))
                    remote_ssh.close()
                else:
                    code = 1
            if code == 0:
                return True
            self.ssh.execute('sleep 2')
        return False

    def render_configs(self):
        self._resolve_hostnames()

        # NN1 先完成配置渲染，non-NN1 节点等待 NN1 信号后再渲染
        nn1_done_flag = os.path.join(self.component_dir, '.nn1.done')
        if not self._is_nn1 and self._nn1_host:
            self.logger.info('[%s@%s] 等待 NN1 (%s) 完成配置...', self.name, self.ssh.host, self._nn1_host)
            if not self._wait_for_remote_file(self._nn1_host, nn1_done_flag, timeout=180):
                raise RuntimeError('[{}@{}] 等待 NN1 配置超时'.format(self.name, self.ssh.host))

        # 备份旧配置（带时间戳）
        conf_dir = os.path.join(self.component_dir, 'etc', 'hadoop')
        timestamp = time.strftime('.bak.%Y%m%d_%H%M%S')
        self.logger.info('[%s@%s] 备份原 Hadoop 配置目录，创建新配置目录', self.name, self.ssh.host)
        self.ssh.execute('mv {d} {d}{t} 2>/dev/null; mkdir -p {d}'.format(
            d=shlex.quote(conf_dir), t=timestamp))

        super().render_configs()

        hadoop_hosts = self._hadoop_hosts
        slaves_content = '\n'.join(hadoop_hosts)
        self.logger.info('[%s@%s] 生成 slaves 文件，节点: %s', self.name, self.ssh.host, ', '.join(hadoop_hosts))
        self.write_remote_file(os.path.join(conf_dir, 'slaves'), slaves_content)

        # 生成 hadoop.sh 启停脚本
        hostname_map = getattr(self.ctx, 'hostname_map', {}) or {}
        def resolve(ip):
            return hostname_map.get(ip, ip)
        hh = self._hadoop_hosts
        n2 = resolve(hh[1]) if len(hh) >= 2 else (resolve(hh[0]) if hh else '')
        C = self.component_dir
        hadoop_sh = '''#!/bin/bash
case $1 in
"start")
    {c}/sbin/start-dfs.sh
    {c}/sbin/start-yarn.sh
    ssh {n2} "{c}/sbin/yarn-daemon.sh start resourcemanager"
    {c}/sbin/hadoop-daemon.sh start zkfc
    ssh {n2} "{c}/sbin/hadoop-daemon.sh start zkfc"
    {c}/sbin/mr-jobhistory-daemon.sh start historyserver
;;

"stop")
    {c}/sbin/mr-jobhistory-daemon.sh stop historyserver
    ssh {n2} "{c}/sbin/yarn-daemon.sh stop resourcemanager"
    {c}/sbin/hadoop-daemon.sh stop zkfc
    ssh {n2} "{c}/sbin/hadoop-daemon.sh stop zkfc"
    {c}/sbin/stop-yarn.sh
    {c}/sbin/stop-dfs.sh
;;
esac'''.format(c=C, n2=n2)
        self.logger.info('[%s@%s] 生成 hadoop.sh 启停脚本', self.name, self.ssh.host)
        self.write_remote_file(os.path.join(self.component_dir, 'hadoop.sh'), hadoop_sh)
        self.ssh.execute('chmod +x {}'.format(shlex.quote(os.path.join(self.component_dir, 'hadoop.sh'))))

        # NN1 写入完成标记
        if self._is_nn1:
            self.ssh.execute('touch {}'.format(shlex.quote(nn1_done_flag)))

        # 等待所有节点完成配置（最多 180 秒）
        if self._is_nn1:
            self.logger.info('[%s@%s] 等待所有 Hadoop 节点完成配置...', self.name, self.ssh.host)
            node_done_flags = [os.path.join(self.component_dir, 'etc', 'hadoop', 'slaves')]
            for host in hadoop_hosts:
                for flag in node_done_flags:
                    if not self._wait_for_remote_file(host, flag, timeout=180):
                        raise RuntimeError('[{}@{}] 节点 {} 配置超时'.format(
                            self.name, self.ssh.host, host))

        # 所有节点都完成配置后，写入 config-done 标记
        done_flag = os.path.join(self.component_dir, '.config.done')
        self.ssh.execute('touch {}'.format(shlex.quote(done_flag)))

    def _ensure_ssh_config(self):
        """在每台 Hadoop 节点当前用户下写入 ~/.ssh/config，使跨节点 SSH 调用
        自动使用 config.yaml servers 中配置的 SSH 端口（22 端口不可用时必需）。

        同时写入主机名条目（Host + HostName + Port）和 IP 条目（Host + Port），
        保证节点间无论用主机名还是 IP 发起 SSH 都能命中正确的端口。
        幂等：先删除旧的自动生成块再追加，保留用户已有的其它配置。
        """
        self._resolve_hostnames()
        servers_map = getattr(self.ctx, 'servers_map', {}) or {}
        hostname_map = getattr(self.ctx, 'hostname_map', {}) or {}
        hosts = self._hadoop_hosts
        if not hosts:
            return
        current_user = getattr(self.ssh, 'username', None) or 'root'
        default_port = getattr(self.ssh, 'port', None) or 22
        lines = ['# BEGIN hadoop-install-ssh-config (auto-generated)',
                 '# SSH 端口来自 config.yaml servers 配置',
                 'StrictHostKeyChecking no',
                 'UserKnownHostsFile /dev/null']
        for h in sorted(hosts):
            si = servers_map.get(h) or {}
            port = si.get('port', default_port)
            user = si.get('username', current_user)
            user_line = ['    User {}'.format(user)] if user and user != current_user else []
            hostname = hostname_map.get(h, h)
            if hostname != h:
                lines.append('')
                lines.append('Host {}'.format(hostname))
                lines.append('    HostName {}'.format(h))
                lines.append('    Port {}'.format(port))
                lines.extend(user_line)
            lines.append('')
            lines.append('Host {}'.format(h))
            lines.append('    Port {}'.format(port))
            lines.extend(user_line)
        lines.append('')
        lines.append('# END hadoop-install-ssh-config')
        content = '\n'.join(lines) + '\n'
        encoded = base64.b64encode(content.encode()).decode()
        port_desc = ', '.join(
            '{}:{}'.format(h, (servers_map.get(h) or {}).get('port', default_port))
            for h in sorted(hosts))
        self.logger.info('[%s@%s] 写入 ~/.ssh/config（Hadoop 节点 SSH 端口: %s）',
                         self.name, self.ssh.host, port_desc)
        cmd = (
            'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
            'touch ~/.ssh/config && chmod 600 ~/.ssh/config && '
            "sed -i '/# BEGIN hadoop-install-ssh-config/,/# END hadoop-install-ssh-config/d' ~/.ssh/config && "
            "echo '{enc}' | base64 -d >> ~/.ssh/config"
        ).format(enc=encoded)
        self.ssh.execute(cmd, check=True, log_command=False)

    def install(self, skip_health_check=False):
        # 先准备（创建目录、解压、渲染配置）
        self.logger.info('[%s@%s] === 开始安装 ===', self.name, self.ssh.host)
        self._ensure_ssh_config()
        self.prepare()
        # 注册 systemd unit（在 start_service 前，后续 daemon 通过 systemctl 启动）
        self._register_hadoop_systemd()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self.logger.info('[%s@%s] === 安装完成 ===', self.name, self.ssh.host)

    def start_service(self):
        # ========== 启动前屏障：等待所有 Hadoop 节点完成配置 ==========
        config_done_flag = os.path.join(self.component_dir, '.config.done')
        if self._is_nn1:
            self.logger.info('[%s@%s] 等待所有 Hadoop 节点完成配置...', self.name, self.ssh.host)
            for host in self._hadoop_hosts:
                if not self._wait_for_remote_file(host, config_done_flag, timeout=180):
                    raise RuntimeError('[{}@{}] 节点 {} 配置超时'.format(
                        self.name, self.ssh.host, host))
            self.logger.info('[%s@%s] 所有节点配置已就绪，开始启动 Hadoop 服务',
                             self.name, self.ssh.host)

        BIN = os.path.join(self.component_dir, 'bin')
        SBIN = os.path.join(self.component_dir, 'sbin')

        if not self._is_nn1:
            self.logger.info('[%s@%s] 等待 NN1 (%s) 通过网络控制本机服务启动',
                             self.name, self.ssh.host, self._nn1_host)
            return

        # ========== 从模板中读取端口配置 ==========
        zk_port = self._get_port_from_template(
            'zookeeper/conf/zoo.cfg',
            [r'clientPort=(\d+)'],
            default=2181
        )
        nn_rpc_port = self._get_port_from_template(
            'hadoop/etc/hadoop/hdfs-site.xml',
            [r'<name>dfs\.namenode\.rpc-address\.psons\.nn[12]</name>\s*<value>[^:]*:(\d+)</value>',
             r'<name>dfs\.namenode\.rpc-address\.</name>\s*<value>[^:]*:(\d+)</value>'],
            default=8020
        )
        jn_port = self._get_port_from_template(
            'hadoop/etc/hadoop/hdfs-site.xml',
            [r'<name>dfs\.journalnode\.rpc-address</name>\s*<value>[^:]*:(\d+)</value>'],
            default=8485
        )
        rm_port = self._get_port_from_template(
            'hadoop/etc/hadoop/yarn-site.xml',
            [r'<name>yarn\.resourcemanager\.address</name>\s*<value>[^:]*:(\d+)</value>',
             r'<name>yarn\.resourcemanager\.resource-tracker\.address</name>\s*<value>[^:]*:(\d+)</value>'],
            default=8032
        )

        # ========== NN1 编排完整启动流程 ==========

        hadoop_hosts = self._hadoop_hosts
        nn1_host = self._nn1_host
        nn2_host = self._nn2_host
        zk_hosts = get_zookeeper_cluster_hosts(getattr(self.ctx, 'comp_hosts', {}))

        # 1. 格式化 ZKFC（仅 NN1 执行一次，需要 ZK 已就绪）
        for zk in zk_hosts:
            self.wait_for_port(zk, zk_port)
        self.logger.info('[%s@%s] 格式化 ZKFC', self.name, self.ssh.host)
        self.ssh.execute('{b}/hdfs zkfc -formatZK -force 2>&1'.format(b=BIN))

        if self._use_systemd:
            # ── systemd 路径（原逻辑，保持不变）──
            # 2. 启动 JournalNode 集群（通过 systemctl）
            self.logger.info('[%s@%s] 启动 JournalNode 集群', self.name, self.ssh.host)
            for host in hadoop_hosts:
                if host == self.ssh.host:
                    self.ssh.execute('sudo systemctl start hadoop-journalnode')
                else:
                    self.ssh.execute('ssh {h} "sudo systemctl start hadoop-journalnode"'.format(h=host))
            for host in hadoop_hosts:
                self.wait_for_port(host, jn_port, timeout=90)

            # 3. 格式化 NameNode（单次初始化，不使用 systemd）
            self.logger.info('[%s@%s] 格式化 NameNode', self.name, self.ssh.host)
            self.ssh.execute('{b}/hadoop namenode -format -force 2>&1'.format(b=BIN))

            # 4. 启动 NameNode（NN1，通过 systemctl）
            self.logger.info('[%s@%s] 启动 NameNode', self.name, self.ssh.host)
            self.ssh.execute('sudo systemctl start hadoop-namenode')
            self.wait_for_port(nn1_host, nn_rpc_port, timeout=90)

            # 5. NN2：Bootstrap Standby + 启动 NameNode（bootstrap 为单次初始化，启动通过 systemctl）
            if nn2_host:
                self.logger.info('[%s@%s] Bootstrap Standby NameNode (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "echo Y | {b}/hdfs namenode -bootstrapStandby 2>&1"'.format(h=nn2_host, b=BIN))
                self.logger.info('[%s@%s] 启动 NameNode (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "sudo systemctl start hadoop-namenode"'.format(h=nn2_host))
                self.wait_for_port(nn2_host, nn_rpc_port, timeout=90)

            # 6. 启动 DataNode 集群（通过 systemctl）
            self.logger.info('[%s@%s] 启动 DataNode 集群', self.name, self.ssh.host)
            for host in hadoop_hosts:
                if host == self.ssh.host:
                    self.ssh.execute('sudo systemctl start hadoop-datanode')
                else:
                    self.ssh.execute('ssh {h} "sudo systemctl start hadoop-datanode"'.format(h=host))

            # 7. 启动 ZKFC（NN1，通过 systemctl）
            for zk in zk_hosts:
                self.wait_for_port(zk, zk_port)
            self.logger.info('[%s@%s] 启动 ZKFC', self.name, self.ssh.host)
            self.ssh.execute('sudo systemctl start hadoop-zkfc')

            # 8. 启动 ZKFC（NN2，通过 systemctl）
            if nn2_host:
                self.logger.info('[%s@%s] 启动 ZKFC (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "sudo systemctl start hadoop-zkfc"'.format(h=nn2_host))

            # 9. 启动 YARN（ResourceManager + NodeManager，通过 systemctl）
            self.logger.info('[%s@%s] 启动 ResourceManager', self.name, self.ssh.host)
            self.ssh.execute('sudo systemctl start hadoop-resourcemanager')
            self.wait_for_port(nn1_host, rm_port, timeout=90)
            self.logger.info('[%s@%s] 启动 NodeManager 集群', self.name, self.ssh.host)
            for host in hadoop_hosts:
                if host == self.ssh.host:
                    self.ssh.execute('sudo systemctl start hadoop-nodemanager')
                else:
                    self.ssh.execute('ssh {h} "sudo systemctl start hadoop-nodemanager"'.format(h=host))

            # 10. 启动 ResourceManager（NN2 作为 Standby RM，通过 systemctl）
            if nn2_host:
                self.logger.info('[%s@%s] 启动 ResourceManager (Standby) (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "sudo systemctl start hadoop-resourcemanager"'.format(h=nn2_host))

            # 11. 启动 JobHistory Server（通过 systemctl）
            self.logger.info('[%s@%s] 启动 JobHistory Server', self.name, self.ssh.host)
            self.ssh.execute('sudo systemctl start hadoop-jobhistory')
        else:
            # ── daemon 脚本路径（降级，无 sudo）──
            # 2. 启动 JournalNode 集群（daemon 脚本，跨节点）
            self.logger.info('[%s@%s] 启动 JournalNode 集群（daemon 脚本）', self.name, self.ssh.host)
            self.ssh.execute('{s}/hadoop-daemons.sh start journalnode 2>&1'.format(s=SBIN))
            for host in hadoop_hosts:
                self.wait_for_port(host, jn_port, timeout=90)

            # 3. 格式化 NameNode
            self.logger.info('[%s@%s] 格式化 NameNode', self.name, self.ssh.host)
            self.ssh.execute('{b}/hadoop namenode -format -force 2>&1'.format(b=BIN))

            # 4. 启动 NameNode（NN1）
            self.logger.info('[%s@%s] 启动 NameNode', self.name, self.ssh.host)
            self.ssh.execute('{s}/hadoop-daemon.sh start namenode 2>&1'.format(s=SBIN))
            self.wait_for_port(nn1_host, nn_rpc_port, timeout=90)

            # 5. NN2：Bootstrap Standby + 启动 NameNode
            if nn2_host:
                self.logger.info('[%s@%s] Bootstrap Standby NameNode (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "echo Y | {b}/hdfs namenode -bootstrapStandby 2>&1"'.format(h=nn2_host, b=BIN))
                self.logger.info('[%s@%s] 启动 NameNode (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "{s}/hadoop-daemon.sh start namenode 2>&1"'.format(h=nn2_host, s=SBIN))
                self.wait_for_port(nn2_host, nn_rpc_port, timeout=90)

            # 6. 启动 DataNode 集群（daemon 脚本，跨节点）
            self.logger.info('[%s@%s] 启动 DataNode 集群', self.name, self.ssh.host)
            self.ssh.execute('{s}/hadoop-daemons.sh start datanode 2>&1'.format(s=SBIN))

            # 7. 启动 ZKFC（NN1）
            for zk in zk_hosts:
                self.wait_for_port(zk, zk_port)
            self.logger.info('[%s@%s] 启动 ZKFC', self.name, self.ssh.host)
            self.ssh.execute('{s}/hadoop-daemon.sh start zkfc 2>&1'.format(s=SBIN))

            # 8. 启动 ZKFC（NN2）
            if nn2_host:
                self.logger.info('[%s@%s] 启动 ZKFC (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "{s}/hadoop-daemon.sh start zkfc 2>&1"'.format(h=nn2_host, s=SBIN))

            # 9. 启动 YARN（ResourceManager + NodeManager，daemon 脚本跨节点）
            self.logger.info('[%s@%s] 启动 YARN 集群', self.name, self.ssh.host)
            self.ssh.execute('{s}/start-yarn.sh 2>&1'.format(s=SBIN))
            self.wait_for_port(nn1_host, rm_port, timeout=90)

            # 10. 启动 ResourceManager（NN2 Standby）
            if nn2_host:
                self.logger.info('[%s@%s] 启动 ResourceManager (Standby) (%s)', self.name, self.ssh.host, nn2_host)
                self.ssh.execute('ssh {h} "{s}/yarn-daemon.sh start resourcemanager 2>&1"'.format(h=nn2_host, s=SBIN))

            # 11. 启动 JobHistory Server
            self.logger.info('[%s@%s] 启动 JobHistory Server', self.name, self.ssh.host)
            self.ssh.execute('{s}/mr-jobhistory-daemon.sh start historyserver 2>&1'.format(s=SBIN))

    def health_check(self):
        """验证 HDFS 和 YARN 状态（NN1 统一检查）"""
        if not self._is_nn1:
            self.logger.info('[%s@%s] 由 NN1 统一做健康检查，本机跳过', self.name, self.ssh.host)
            return
        checker = HadoopChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
        self.logger.info('[%s@%s] HDFS 健康检查通过', self.name, self.ssh.host)
        self.logger.info('[%s@%s] YARN 健康检查通过', self.name, self.ssh.host)

    def _register_hadoop_systemd(self):
        if not self._is_nn1:
            return

        cd_q = shlex.quote(self.component_dir)
        jh_q = shlex.quote(self.java_home)
        pd_q = shlex.quote(os.path.join(self.component_dir, 'data', 'pids'))
        hadoop_hosts = self._hadoop_hosts
        servers_map = getattr(self.ctx, 'servers_map', {}) or {}
        nn1_host = self._nn1_host
        nn2_host = self._nn2_host

        def _unit_content(role):
            templates = {
                'hadoop-namenode': (
                    '[Unit]\n'
                    'Description=Hadoop NameNode\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/hadoop-daemon.sh start namenode\n'
                    'ExecStop={cd}/sbin/hadoop-daemon.sh stop namenode\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/hadoop-root-namenode.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-journalnode': (
                    '[Unit]\n'
                    'Description=Hadoop JournalNode\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/hadoop-daemon.sh start journalnode\n'
                    'ExecStop={cd}/sbin/hadoop-daemon.sh stop journalnode\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/hadoop-root-journalnode.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-datanode': (
                    '[Unit]\n'
                    'Description=Hadoop DataNode\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/hadoop-daemon.sh start datanode\n'
                    'ExecStop={cd}/sbin/hadoop-daemon.sh stop datanode\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/hadoop-root-datanode.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-zkfc': (
                    '[Unit]\n'
                    'Description=Hadoop ZKFC\n'
                    'After=network.target\n'
                    'After=hadoop-namenode.service hadoop-journalnode.service\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/hadoop-daemon.sh start zkfc\n'
                    'ExecStop={cd}/sbin/hadoop-daemon.sh stop zkfc\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/hadoop-root-zkfc.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-resourcemanager': (
                    '[Unit]\n'
                    'Description=Hadoop ResourceManager\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/yarn-daemon.sh start resourcemanager\n'
                    'ExecStop={cd}/sbin/yarn-daemon.sh stop resourcemanager\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/yarn-root-resourcemanager.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-nodemanager': (
                    '[Unit]\n'
                    'Description=Hadoop NodeManager\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/yarn-daemon.sh start nodemanager\n'
                    'ExecStop={cd}/sbin/yarn-daemon.sh stop nodemanager\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/yarn-root-nodemanager.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
                'hadoop-jobhistory': (
                    '[Unit]\n'
                    'Description=Hadoop JobHistory Server\n'
                    'After=network.target\n'
                    '\n'
                    '[Service]\n'
                    'Type=forking\n'
                    'Environment=JAVA_HOME={jh}\n'
                    'Environment=HADOOP_CONF_DIR={cd}/etc/hadoop\n'
                    'ExecStart={cd}/sbin/mr-jobhistory-daemon.sh start historyserver\n'
                    'ExecStop={cd}/sbin/mr-jobhistory-daemon.sh stop historyserver\n'
                    'Restart=on-failure\n'
                    'User=root\n'
                    'PIDFile={pd}/hadoop-root-historyserver.pid\n'
                    '\n'
                    '[Install]\n'
                    'WantedBy=multi-user.target\n'
                ),
            }
            return templates[role].format(cd=cd_q, jh=jh_q, pd=pd_q)

        def _host_roles(host):
            roles = ['hadoop-journalnode', 'hadoop-datanode', 'hadoop-nodemanager']
            if host == nn1_host or host == nn2_host:
                roles += ['hadoop-namenode', 'hadoop-zkfc', 'hadoop-resourcemanager']
            if host == nn1_host:
                roles.append('hadoop-jobhistory')
            return roles

        for host in hadoop_hosts:
            if host == self.ssh.host:
                ssh = self.ssh
                need_close = False
            else:
                si = servers_map.get(host)
                if not si:
                    self.logger.warning('[%s@%s] 未找到主机 %s 的连接信息，跳过 systemd 注册',
                                        self.name, self.ssh.host, host)
                    continue
                from core.ssh_client import get_ssh_client
                ssh = get_ssh_client(si, dry_run=self.ssh.dry_run, logger=self.logger)
                need_close = True

            roles = _host_roles(host)
            service_user = getattr(ssh, 'username', None) or 'root'
            for role in roles:
                content = _unit_content(role)
                content = content.replace('User=root', 'User={}'.format(service_user))
                content = content.replace('hadoop-root-', 'hadoop-{}-'.format(service_user))
                content = content.replace('yarn-root-', 'yarn-{}-'.format(service_user))
                encoded = base64.b64encode(content.encode()).decode()
                if self._use_systemd:
                    remote_path = '/etc/systemd/system/{}.service'.format(role)
                    remote_q = shlex.quote(remote_path)
                    ssh.execute("echo '{}' | base64 -d | sudo tee {} > /dev/null".format(encoded, remote_q), check=True, log_command=False)
                    ssh.execute('sudo chmod 644 {}'.format(remote_q))
                else:
                    # 无 sudo：归档到 {install_dir}/systemd/
                    archive_dir = os.path.join(self.install_dir, 'systemd')
                    ssh.execute('mkdir -p {}'.format(shlex.quote(archive_dir)))
                    archive_path = os.path.join(archive_dir, '{}.service'.format(role))
                    ssh.execute("echo '{}' | base64 -d > {}".format(encoded, shlex.quote(archive_path)), check=True, log_command=False)
                    ssh.execute('chmod 644 {}'.format(shlex.quote(archive_path)))

            if self._use_systemd:
                ssh.execute('sudo systemctl daemon-reload')
                for role in roles:
                    ssh.execute('sudo systemctl enable {}'.format(role))

            if need_close:
                ssh.close()
        self.logger.info('[%s@%s] Hadoop systemd 单元注册完成', self.name, self.ssh.host)
