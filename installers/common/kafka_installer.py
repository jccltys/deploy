# -*- coding: utf-8 -*-
"""
Kafka 安装器 — 集群模式
每台主机生成唯一的 broker.id，通过 kafka-server-start 启动
"""
import os
import re
import shlex

from installers.common.base_installer import BaseInstaller
from utils.health import KafkaChecker
from core.config_utils import get_zookeeper_cluster_hosts, get_component_config, get_kafka_vars


class KafkaInstaller(BaseInstaller):
    GROUP = 'common'
    REQUIRES_ZK_CHECK = True

    @classmethod
    def get_template_vars_doc(cls):
        base = super(KafkaInstaller, cls).get_template_vars_doc()
        base.update({
            'broker_id': {
                'type': 'str',
                'description': 'Kafka broker ID',
                'source': '自动分配（按主机名排序 0, 1, 2...）',
                'example': '0',
            },
            'zookeeper_connect': {
                'type': 'str',
                'description': 'ZooKeeper 连接串',
                'source': '自动从 deploy 映射推导',
                'example': 'node1:2181,node2:2181,node3:2181',
            },
        })
        return base

    def _prepare_cluster_config(self):
        if getattr(self.ctx, 'broker_ids', None):
            return
        sorted_hosts = sorted(getattr(self.ctx, 'comp_hosts', {}).get('kafka', []))
        self.ctx.broker_ids = {h: i for i, h in enumerate(sorted_hosts)}
        zk_hosts = get_zookeeper_cluster_hosts(getattr(self.ctx, 'comp_hosts', {}))
        zk_cfg = get_component_config(self.config, 'zookeeper')
        zk_port = zk_cfg.get('port', 2181)
        if zk_hosts:
            self.ctx.zookeeper_connect = ','.join('{}:{}'.format(h, zk_port) for h in zk_hosts)
        else:
            self.ctx.zookeeper_connect = 'localhost:{}'.format(zk_port)

    def template_vars(self, **overrides):
        self._prepare_cluster_config()
        broker_ids = getattr(self.ctx, 'broker_ids', {}) or {}
        broker_id = broker_ids.get(self.ssh.host, 0)
        kafka_vars = get_kafka_vars(self.ctx, self.config) or {}
        overrides.setdefault('broker_id', str(broker_id))
        overrides.setdefault('zookeeper_connect',
                             getattr(self.ctx, 'zookeeper_connect', 'localhost:2181'))
        overrides.setdefault('kafka_port', str(kafka_vars.get('kafka_port', 9092)))
        return super().template_vars(**overrides)

    def start_service(self):
        self._prepare_cluster_config()
        zk_connect = getattr(self.ctx, 'zookeeper_connect', 'localhost:2181')
        for hostport in zk_connect.split(','):
            host, port = hostport.strip().rsplit(':', 1)
            self.wait_for_port(host, int(port))
        self.logger.info('[%s@%s] 启动 Kafka', self.name, self.ssh.host)
        cd = shlex.quote(self.component_dir)
        jh = shlex.quote(self.java_home)
        unit = '''[Unit]
Description=Kafka
After=network.target zookeeper.service

[Service]
Type=simple
Environment=JAVA_HOME={jh}
ExecStart={cd}/bin/kafka-server-start.sh {cd}/config/server.properties
ExecStop={cd}/bin/kafka-server-stop.sh
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
'''.format(jh=jh, cd=cd)
        self._create_systemd_unit('kafka', unit)
        if self._use_systemd:
            self._enable_systemd_unit('kafka', start=True)
        else:
            self._script_start('export JAVA_HOME={} && {}/bin/kafka-server-start.sh -daemon {}/config/server.properties'.format(jh, cd, cd))

    def health_check(self):
        checker = KafkaChecker(self.ssh, self.component_dir, self.config, self.logger)
        checker.check()
