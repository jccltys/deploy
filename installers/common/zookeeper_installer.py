# -*- coding: utf-8 -*-
"""
Zookeeper 安装器 — 支持自动判断集群/单节点模式
- 节点数 > 2：使用前 3 个 IP 部署集群（生成 myid + server.x 配置）
- 节点数 <= 2：单节点模式
通过 zkServer.sh 启动
"""
import os
import shlex

from installers.common.base_installer import BaseInstaller
from utils.health import ZookeeperChecker
from core.config_utils import get_zookeeper_vars


class ZookeeperInstaller(BaseInstaller):
    GROUP = 'common'

    @classmethod
    def get_template_vars_doc(cls):
        base = super(ZookeeperInstaller, cls).get_template_vars_doc()
        base.update({
            'zk_servers': {
                'type': 'str',
                'description': 'Zookeeper 集群节点配置（server.1, server.2, server.3）',
                'source': '自动从 deploy 映射推导（节点数>2时使用前3个IP）',
                'example': 'server.1=192.168.1.2:2888:3888\\nserver.2=192.168.1.3:2888:3888\\nserver.3=192.168.1.4:2888:3888',
            },
            'myid': {
                'type': 'str',
                'description': '当前主机的 Zookeeper 节点 ID',
                'source': '自动分配（1, 2, 3...）',
                'example': '1',
            },
        })
        return base

    def _get_zk_hosts(self):
        """获取 zookeeper 主机列表"""
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('zookeeper', []))

    def _is_cluster(self):
        """判断是否为集群模式（节点数 > 2）"""
        return len(self._get_zk_hosts()) > 2

    def _get_myid(self):
        """计算当前主机的 myid（集群模式下）"""
        hosts = self._get_zk_hosts()
        if self._is_cluster():
            try:
                return str(hosts.index(self.ssh.host) + 1)
            except ValueError:
                return '1'
        return '1'

    def template_vars(self, **overrides):
        hosts = self._get_zk_hosts()
        zk_vars = get_zookeeper_vars(self.ctx, self.config) or {}
        overrides.setdefault('zookeeper_port', str(zk_vars.get('zookeeper_port', 2181)))
        overrides.setdefault('zookeeper_admin_port', str(zk_vars.get('zookeeper_admin_port', 8081)))
        zk_election_port = zk_vars.get('zookeeper_election_port', 2888)
        zk_quorum_port = zk_vars.get('zookeeper_quorum_port', 3888)
        if self._is_cluster():
            # 集群模式：使用前3个IP
            cluster_hosts = hosts[:3]
            servers = []
            for i, host in enumerate(cluster_hosts, 1):
                servers.append('server.{}={}:{}:{}'.format(i, host, zk_election_port, zk_quorum_port))
            overrides.setdefault('zk_servers', '\n'.join(servers))
            overrides.setdefault('myid', self._get_myid())
        else:
            # 单节点模式：不生成集群配置
            overrides.setdefault('zk_servers', '')
            overrides.setdefault('myid', '1')
        return super().template_vars(**overrides)

    def install(self, skip_health_check=False):
        """覆盖基类 install，根据集群/单节点模式决定是否跳过"""
        hosts = self._get_zk_hosts()
        if not hosts:
            self.logger.warning('[%s@%s] 未配置 zookeeper 主机，跳过安装',
                               self.name, self.ssh.host)
            return

        if self._is_cluster():
            # 集群模式：只有前 3 台执行安装
            cluster_hosts = hosts[:3]
            if self.ssh.host not in cluster_hosts:
                self.logger.info('[%s@%s] 当前主机不在集群运行节点中（集群模式仅前 3 台运行），跳过安装',
                                self.name, self.ssh.host)
                return
            self.logger.info('[%s@%s] 集群模式，运行节点: %s，当前为 server.%d',
                            self.name, self.ssh.host,
                            ', '.join(cluster_hosts),
                            cluster_hosts.index(self.ssh.host) + 1)
        else:
            # 单节点模式：只有第 1 台执行安装
            if self.ssh.host != hosts[0]:
                self.logger.info('[%s@%s] 单节点模式，仅第 1 台主机运行 ZK（%s），当前主机跳过安装',
                                self.name, self.ssh.host, hosts[0])
                return
            self.logger.info('[%s@%s] 单节点模式，当前主机为运行节点',
                            self.name, self.ssh.host)

        super().install(skip_health_check=skip_health_check)

    def _create_data_dirs(self):
        super()._create_data_dirs()
        # 集群模式下创建 myid 文件
        if self._is_cluster():
            myid = self._get_myid()
            myid_file = os.path.join(self.data_dir, 'myid')
            self.logger.info('[%s@%s] 集群模式，创建 myid 文件: %s',
                            self.name, self.ssh.host, myid)
            self.write_remote_file(myid_file, myid + '\n')

    def start_service(self):
        mode = '集群' if self._is_cluster() else '单节点'
        self.logger.info('[%s@%s] 启动 Zookeeper（%s模式）', self.name, self.ssh.host, mode)
        cd = shlex.quote(self.component_dir)
        jh = shlex.quote(self.java_home)
        unit = '''[Unit]
Description=ZooKeeper
After=network.target

[Service]
Type=simple
Environment=JAVA_HOME={jh}
ExecStart={cd}/bin/zkServer.sh start-foreground
ExecStop={cd}/bin/zkServer.sh stop
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(jh=jh, cd=cd)
        self._create_systemd_unit('zookeeper', unit)
        if self._use_systemd:
            self._enable_systemd_unit('zookeeper', start=True)
        else:
            self._script_start('export JAVA_HOME={} && {}/bin/zkServer.sh start'.format(jh, cd))

    def health_check(self):
        checker = ZookeeperChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
        self.logger.info('[%s@%s] Zookeeper 健康检查通过', self.name, self.ssh.host)
