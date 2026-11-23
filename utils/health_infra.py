# -*- coding: utf-8 -*-
"""基础设施组件健康检查器"""
import os
import shlex

from core.ckman_api import ckman_login, ckman_get_cluster
from core.config_utils import get_component_config
from .health_base import HealthChecker, check_port, check_process


class RedisChecker(HealthChecker):
    def __init__(self, ssh_client, component_dir, config=None, logger=None, password=None):
        super().__init__(ssh_client, component_dir, config, logger)
        if password is not None:
            self.password = password
        elif config is not None:
            redis_cfg = get_component_config(config, 'redis')
            self.password = redis_cfg.get('password', 'Redis@123')
        else:
            self.password = 'Redis@123'

    def check(self):
        redis_cfg = get_component_config(self.config, 'redis')
        port = redis_cfg.get('port', 6379)
        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        cmd = '{}/bin/redis-cli -a {} -p {} ping 2>&1'.format(
            shlex.quote(self.component_dir), self.password, port)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd)
        code, out, _ = self.ssh.execute(cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'PONG' not in out:
            raise RuntimeError('Redis 未响应 PONG: {}'.format(out.strip()[:200]))
        return True


class RedisSentinelChecker(HealthChecker):
    def __init__(self, ssh_client, component_dir, config=None, logger=None):
        super().__init__(ssh_client, component_dir, config, logger)
        redis_cfg = get_component_config(self.config, 'redis')
        self.port = redis_cfg.get('sentinel_port', 26379)
        self.sentinel_name = redis_cfg.get('sentinel_name', 'mymaster')

    def check(self):
        check_port(self.ssh, self.ssh.host, self.port, timeout=30, logger=self.logger)
        # sentinel ping - no auth required
        ping_cmd = '{}/bin/redis-cli -p {} ping 2>&1'.format(
            shlex.quote(self.component_dir), self.port)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', ping_cmd)
        code, out, _ = self.ssh.execute(ping_cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'PONG' not in out:
            raise RuntimeError('Redis Sentinel 未响应 PONG: {}'.format(out.strip()[:200]))
        # verify master name
        master_cmd = '{}/bin/redis-cli -p {} sentinel master {} 2>&1'.format(
            shlex.quote(self.component_dir), self.port, self.sentinel_name)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', master_cmd)
        code, out, _ = self.ssh.execute(master_cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or self.sentinel_name not in out:
            raise RuntimeError('Redis Sentinel master 验证失败: {}'.format(out.strip()[:200]))
        return True


class NginxChecker(HealthChecker):
    def check(self):
        nginx_cfg = get_component_config(self.config, 'nginx')
        port = nginx_cfg.get('listen_port', 80)
        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] nginx 端口 %d 监听正常', port)
        return True


class ZookeeperChecker(HealthChecker):
    def check(self):
        zk_cfg = get_component_config(self.config, 'zookeeper')
        port = zk_cfg.get('port', 2181)
        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        java_home = os.path.join(os.path.dirname(self.component_dir), 'java')
        cmd = 'export JAVA_HOME={} && {}/bin/zkServer.sh status 2>&1'.format(
            shlex.quote(java_home), shlex.quote(self.component_dir))
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd)
        code, out, _ = self.ssh.execute(cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'Mode:' not in out:
            raise RuntimeError('Zookeeper 状态异常: {}'.format(out.strip()[:200]))
        return True


class KafkaChecker(HealthChecker):
    def check(self):
        kafka_cfg = get_component_config(self.config, 'kafka')
        port = kafka_cfg.get('port', 9092)
        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] Kafka 端口 %d 监听正常', port)
        return True


class MySQLChecker(HealthChecker):
    def __init__(self, ssh_client, component_dir, config=None, logger=None, password=None):
        super().__init__(ssh_client, component_dir, config, logger)
        mysql_cfg = get_component_config(config, 'mysql') if config is not None else {}
        self.port = mysql_cfg.get('port', 3306)
        if password is not None:
            self.password = password
        elif config is not None:
            self.password = mysql_cfg.get('password', 'MySQL@123')
        else:
            self.password = 'MySQL@123'

    def check(self):
        check_port(self.ssh, self.ssh.host, self.port, timeout=30, logger=self.logger)
        cmd = "{b}/bin/mysql -u root -p'{p}' -P {port} -e \"SELECT 1 AS ok\" 2>&1".format(
            b=shlex.quote(self.component_dir), p=self.password, port=self.port)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd)
        code, out, _ = self.ssh.execute(cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'ok' not in out:
            raise RuntimeError('MySQL 未正确响应: {}'.format(out.strip()[:200]))
        return True


class HadoopChecker(HealthChecker):
    def check(self):
        BIN = os.path.join(self.component_dir, 'bin')
        cmd1 = 'timeout 30 {b}/hdfs dfsadmin -report 2>&1 | head -30'.format(b=BIN)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd1)
        code, out, _ = self.ssh.execute(cmd1)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'Live datanodes' not in out:
            raise RuntimeError('HDFS 状态异常: {}'.format(out.strip()[:200]))
        cmd2 = 'timeout 30 {b}/yarn node -list 2>&1'.format(b=BIN)
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd2)
        code, out, _ = self.ssh.execute(cmd2)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0 or 'RUNNING' not in out:
            raise RuntimeError('YARN 状态异常: {}'.format(out.strip()[:200]))
        return True


class CkmanChecker(HealthChecker):
    def check(self):
        ckman_cfg = get_component_config(self.config, 'ckman')
        port = ckman_cfg.get('port', 8808)
        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] ckman 端口 %d 监听正常', port)
        return True


class ClickHouseChecker(HealthChecker):
    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        if self.context is None:
            raise RuntimeError('ClickHouseChecker 需要 context 参数')

        ckman_hosts = sorted(
            getattr(self.context, 'comp_hosts', {}).get('ckman', []))
        if not ckman_hosts:
            raise RuntimeError('未找到 ckman 主机，无法检查 ClickHouse')
        ckman_host = ckman_hosts[0]

        ckman_cfg = get_component_config(self.config, 'ckman')
        ckman_port = ckman_cfg.get('port', 8808)

        ch_cfg = getattr(self.config, 'clickhouse', {}) or {}
        cluster_name = ch_cfg.get('cluster', 'ckcluster')

        token = ckman_login(ckman_host, ckman_port, 'ckman',
                            'Ckman123456!', self.logger)
        cluster_info = ckman_get_cluster(
            ckman_host, ckman_port, token, cluster_name, self.logger)

        status = cluster_info.get('status', 'unknown')
        nodes = cluster_info.get('nodes', [])
        if status != 'green':
            raise RuntimeError(
                'ClickHouse 集群状态异常: {}'.format(status))
        bad_nodes = [
            n.get('ip', '?') for n in nodes
            if n.get('status') != 'green'
        ]
        if bad_nodes:
            raise RuntimeError(
                'ClickHouse 节点状态异常: {}'.format(bad_nodes))
        if self.logger:
            self.logger.info(
                '[health] ClickHouse 集群 %s 健康'
                '（集群 green，%d 个节点全部 green）',
                cluster_name, len(nodes))
        return True


class NebulaChecker(HealthChecker):
    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 graphd_port=9669):
        super().__init__(ssh_client, component_dir, config, logger)
        # config 中配置的端口优先于参数传入值
        if config is not None:
            nebula_cfg = get_component_config(config, 'nebula')
            self.graphd_port = nebula_cfg.get('graphd_port', graphd_port)
        else:
            self.graphd_port = graphd_port

    def check(self):
        check_port(self.ssh, self.ssh.host, self.graphd_port, timeout=30,
                   logger=self.logger)
        if not check_process(self.ssh, 'nebula-graphd',
                             logger=self.logger):
            raise RuntimeError('nebula-graphd 进程未运行')
        if self.logger:
            self.logger.info(
                '[health] Nebula Graph 端口 %d 监听正常，进程存在',
                self.graphd_port)
        return True


class NebulaStudioChecker(HealthChecker):
    def check(self):
        ns_cfg = get_component_config(self.config, 'nebula_studio')
        port = ns_cfg.get('port', 7001)
        check_port(self.ssh, self.ssh.host, port, timeout=30,
                   logger=self.logger)
        if self.logger:
            self.logger.info(
                '[health] Nebula Studio 端口 %d 监听正常', port)
        return True


class NacosChecker(HealthChecker):
    def check(self):
        host = self.ssh.host
        nacos_cfg = get_component_config(self.config, 'nacos')
        port = nacos_cfg.get('port', 8848)
        url = 'http://{}:{}/nacos/actuator/health'.format(host, port)
        cmd = "curl -s '{}' 2>&1".format(url)
        if self.logger:
            self.logger.info('[health] 执行 Nacos 健康检查: %s', cmd)
        code, out, err = self.ssh.execute(cmd)
        if self.logger:
            self.logger.info('[health] 返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0:
            raise RuntimeError('Nacos 健康检查 curl 失败: {}'.format(err.strip()[:200]))
        if 'UP' not in out or '"status":"UP"' not in out:
            raise RuntimeError('Nacos 状态异常，期望 "UP"，实际: {}'.format(out.strip()[:200]))
        if self.logger:
            self.logger.info('[health] nacos 健康检查通过: %s', out.strip())
        return True


class JavaChecker(HealthChecker):
    def check(self):
        cmd = '{}/bin/java -version 2>&1'.format(shlex.quote(self.component_dir))
        if self.logger:
            self.logger.info('[health] 执行检查: %s', cmd)
        code, out, _ = self.ssh.execute(cmd)
        if self.logger:
            self.logger.info('[health] 命令返回码: %d, 输出: %s', code, out.strip()[:200])
        if code != 0:
            raise RuntimeError('Java 不可执行: {}'.format(out.strip()[:200]))
        return True
