# -*- coding: utf-8 -*-
"""
DolphinScheduler（海豚调度器）安装器

参考官方伪集群/集群部署流程（免密方式）：
1. 上传并解压 DolphinScheduler 二进制包到 apps/odmp/
2. 创建软链接 apps/odmp/dolphinscheduler -> 版本目录
3. 修改配置文件（数据库连接、注册中心、JAVA_HOME 等）
4. 复制 MySQL JDBC 驱动
5. 启动服务（master-server / worker-server / api-server / alert-server）
6. 健康检查（API 端口 12345）

安装目录: {install_dir}/apps/odmp/
运行用户: config.yaml servers 中定义的连接用户（免密）
数据库: odmp（仅记录配置，不初始化）
"""
import os
import re
import shlex
import time

from installers.common.base_installer import BaseInstaller
from core.config_utils import get_odmp_vars, get_component_config, get_zookeeper_vars


class DolphinschedulerInstaller(BaseInstaller):
    GROUP = 'odmp'
    REQUIRES_HADOOP_CONF = True

    @property
    def apps_root(self):
        return os.path.join(self.config.apps_dir, 'odmp')

    @property
    def component_dir(self):
        return os.path.join(self.apps_root, 'dolphinscheduler')

    @property
    def _package_dest_dir(self):
        return self.apps_root

    def _create_dirs(self):
        self.logger.info('[%s@%s] 创建远程目录: %s',
                          self.name, self.ssh.host, self.apps_root)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.apps_root)))

    def _get_cluster_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('dolphinscheduler', [self.ssh.host]))

    def _is_first_host(self):
        return self.ssh.host == self._get_cluster_hosts()[0]

    def _ds_vars(self):
        odmp_vars = get_odmp_vars(self.ctx, self.config) or {}
        zk_vars = get_zookeeper_vars(self.ctx, self.config) or {}
        return {
            'mysql_host': odmp_vars.get('mysql_host', '127.0.0.1'),
            'mysql_port': odmp_vars.get('mysql_port', '3306'),
            'mysql_user': odmp_vars.get('mysql_user', 'root'),
            'mysql_password': odmp_vars.get('mysql_password', 'MySQL@123'),
            'nacos_host': odmp_vars.get('nacos_host', '127.0.0.1:8848'),
            'zookeeper_connect': zk_vars.get('zookeeper_servers', '127.0.0.1:2181'),
            'deploy_user': self.ssh.username,
        }

    @property
    def _hadoop_hosts(self):
        return sorted(getattr(self.ctx, 'comp_hosts', {}).get('hadoop', []))

    def _hadoop_conf_dir(self):
        return os.path.join(self.comms_dir, 'hadoop', 'etc', 'hadoop')

    def _is_hadoop_ha(self):
        return len(self._hadoop_hosts) >= 2

    def _copy_hdfs_configs_to_services(self):
        """从部署机器 HTTP 服务下载 core-site.xml / hdfs-site.xml 到 master 和 worker 的 conf 目录"""
        hadoop_hosts = self._hadoop_hosts
        if not hadoop_hosts or not self._is_hadoop_ha():
            return

        base_url = 'http://{}:{}/hadoop'.format(self.config.host_ip, self.config.http_port)
        self.logger.info('[%s@%s] 从 HTTP 服务下载 HDFS 配置文件', self.name, self.ssh.host)

        for target_subdir in ['master-server/conf', 'worker-server/conf']:
            dst = os.path.join(self.component_dir, target_subdir)
            self.ssh.execute('mkdir -p {}'.format(shlex.quote(dst)))
            for xml_file in ['core-site.xml', 'hdfs-site.xml']:
                url = '{}/{}'.format(base_url, xml_file)
                target = '{}/{}'.format(shlex.quote(dst), xml_file)
                self.ssh.execute(
                    'curl -fsS -o {} {} --retry 3 --retry-delay 5 2>/dev/null || true'.format(
                        target, url), check=False)
        self.logger.info('[%s@%s] HDFS 配置文件拷贝完成', self.name, self.ssh.host)

    def _configure_common_properties(self):
        """修改 master 和 worker 的 common.properties（HDFS、Kerberos）"""
        master_props = 'master-server/conf/common.properties'
        master_path = os.path.join(self.component_dir, master_props)
        code, content, _ = self.ssh.execute(
            'cat {} 2>/dev/null'.format(shlex.quote(master_path)))
        if code != 0:
            self.logger.warning('[%s@%s] 未找到 %s，跳过 common.properties 配置',
                                self.name, self.ssh.host, master_props)
            return

        hadoop_hosts = self._hadoop_hosts
        use_hdfs = len(hadoop_hosts) > 0
        ds_cfg = get_component_config(self.config, 'dolphinscheduler')

        resource_type = 'HDFS' if use_hdfs else ds_cfg.get('resource_storage_type', 'NONE')

        replacements = {
            'resource.storage.type': resource_type,
        }

        if use_hdfs:
            hdfs_default_fs = ds_cfg.get('hdfs_default_fs', 'hdfs://psons')
            replacements['resource.hdfs.fs.defaultFS'] = hdfs_default_fs
            replacements['resource.hdfs.root.user'] = ds_cfg.get('hdfs_root_user', 'hdfs')
            replacements['resource.storage.upload.base.path'] = ds_cfg.get(
                'storage_upload_base_path', self.component_dir)

            # YARN ResourceManager
            hostname_map = getattr(self.ctx, 'hostname_map', {}) or {}
            def _resolve(ip):
                return hostname_map.get(ip, ip)

            rm_http_port = ds_cfg.get('resourcemanager_http_port', '8088')
            history_port = ds_cfg.get('history_server_port', '19888')

            rm_ids = ','.join(_resolve(h) for h in hadoop_hosts[:2])

            replacements['yarn.resourcemanager.ha.rm.ids'] = rm_ids
            replacements['resource.manager.httpaddress.port'] = rm_http_port
            replacements['yarn.job.history.status.address'] = 'http://{0}:{1}/ws/v1/history/mapreduce/jobs/%s'.format(
                _resolve(hadoop_hosts[0]), history_port)

            # Kerberos
            kerberos_enabled = (ds_cfg.get('kerberos_enabled', 'false').lower() == 'true')
            if kerberos_enabled:
                replacements['hadoop.security.authentication'] = 'kerberos'
                replacements['hadoop.security.kerberos.keytab.path'] = ds_cfg.get(
                    'kerberos_keytab_path', '/opt/keytab/dolphinscheduler.keytab')
                replacements['hadoop.security.kerberos.principal'] = ds_cfg.get(
                    'kerberos_principal', 'dolphinscheduler/{}@REALM'.format(self.ssh.host))

        # 逐行替换属性
        lines = content.split('\n')
        new_lines = []
        replaced_keys = set()
        for line in lines:
            stripped = line.strip()
            matched = False
            for key, val in replacements.items():
                if stripped.startswith(key + '=') or stripped.startswith(key + ' '):
                    new_lines.append('{}={}'.format(key, val))
                    replaced_keys.add(key)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        # 追加未在原文件中出现的属性
        for key, val in replacements.items():
            if key not in replaced_keys:
                new_lines.append('{}={}'.format(key, val))

        new_content = '\n'.join(new_lines)
        self.write_remote_file(master_path, new_content)
        self.logger.info('[%s@%s] 已更新: master-server/conf/common.properties',
                          self.name, self.ssh.host)

        # 复制到 worker-server/conf/common.properties（内容一致）
        worker_path = os.path.join(self.component_dir,
                                   'worker-server/conf/common.properties')
        self.ssh.execute('cp {} {}'.format(
            shlex.quote(master_path), shlex.quote(worker_path)))
        self.logger.info('[%s@%s] 已复制到: worker-server/conf/common.properties',
                          self.name, self.ssh.host)

    @staticmethod
    def _export_var(pattern):
        """从 export VAR=xxx 中提取变量名"""
        m = re.match(r'^export\s+(\w+)=', pattern)
        return m.group(1) if m else None

    def _patch_env_file(self, rel_path, replacements):
        """用 sed 在远程主机上原地修改配置行，不追加不存在的行"""
        full_path = os.path.join(self.component_dir, rel_path)
        path_q = shlex.quote(full_path)
        ok = 0
        for old, new in replacements:
            var = self._export_var(old)
            if not var:
                continue
            # 用 | 作为 sed 分隔符避免与 / 冲突，整条表达式用单引号防止 shell 展开
            # 匹配行首可选 export 前缀（dolphinscheduler_env.sh 有 export，install_env.sh 无）
            # & 在 sed 替换中是特殊字符（代表整个匹配文本），需要转义为 \&
            sed_new = new.replace('&', '\\&')
            sed_cmd = "sed -i 's|^\\(export \\)\\?{}.*|{}|' {}".format(var, sed_new, path_q)
            # 确保 sed_new 中不含单引号（若有则需跳出并转义）
            # 当前所有替换值均不含单引号，安全
            self.ssh.execute(sed_cmd, check=False)
            ok += 1
        self.logger.info('[%s@%s] %s: 已修改 %d 项',
                          self.name, self.ssh.host, rel_path, ok)

    def _configure_dolphinscheduler(self):
        self._configure_common_properties()
        ds_vars = self._ds_vars()
        mysql_address = '{}:{}'.format(ds_vars['mysql_host'], ds_vars['mysql_port'])
        java_home_q = self.java_home

        # dolphinscheduler_env.sh（数据库、注册中心、JAVA_HOME）
        self._patch_env_file('bin/env/dolphinscheduler_env.sh', [
            ('export JAVA_HOME=${JAVA_HOME:-/opt/soft/java}',
             'export JAVA_HOME={}'.format(java_home_q)),
            ('export DATABASE=${DATABASE:-postgresql}',
             'export DATABASE=${DATABASE:-mysql}'),
            ('export SPRING_DATASOURCE_URL=',
             'export SPRING_DATASOURCE_URL="jdbc:mysql://{}/odmp?characterEncoding=utf8&useSSL=false&allowMultiQueries=true&serverTimezone=Asia/Shanghai"'.format(mysql_address)),
            ('export SPRING_DATASOURCE_USERNAME=',
             'export SPRING_DATASOURCE_USERNAME=${SPRING_DATASOURCE_USERNAME:-' + ds_vars['mysql_user'] + '}'),
            ('export SPRING_DATASOURCE_PASSWORD=',
             'export SPRING_DATASOURCE_PASSWORD=${SPRING_DATASOURCE_PASSWORD:-' + ds_vars['mysql_password'] + '}'),
            ('export REGISTRY_ZOOKEEPER_CONNECT_STRING=${REGISTRY_ZOOKEEPER_CONNECT_STRING:-localhost:2181}',
             'export REGISTRY_ZOOKEEPER_CONNECT_STRING=${REGISTRY_ZOOKEEPER_CONNECT_STRING:-' + ds_vars['zookeeper_connect'] + '}'),
            ('export DATAX_HOME=${DATAX_HOME:-/opt/soft/datax}',
             'export DATAX_HOME=${DATAX_HOME:-' + self.apps_root + '/datax}'),
        ])

        # install_env.sh（安装路径、部署用户、SSH端口、集群分配）
        all_hosts = self._get_cluster_hosts()
        ips_str = ','.join(all_hosts)
        server_info = (self.ctx.servers_map or {}).get(self.ssh.host, {})
        ssh_port = server_info.get('port', 22)
        deploy_user = server_info.get('username', 'root')
        self._patch_env_file('bin/env/install_env.sh', [
            ('export installPath=${installPath:-~/dolphinscheduler}',
             'installPath=${installPath:-"' + self.component_dir + '"}'),
            ('export deployUser=${deployUser:-dolphinscheduler}',
             'deployUser=${deployUser:-"' + deploy_user + '"}'),
            ('export sshPort=${sshPort:-"22"}',
             'sshPort=${sshPort:-"' + str(ssh_port) + '"}'),
            ('export ips=${ips:-localhost}',
             'ips=${ips:-"' + ips_str + '"}'),
            ('export masters=${masters:-localhost}',
             'masters=${masters:-"' + ips_str + '"}'),
            ('export workers=${workers:-localhost:default}',
             'workers=${workers:-"' + ','.join('{}:default'.format(h) for h in all_hosts) + '"}'),
        ])

    def prepare(self):
        """准备阶段：第一台主机下载解压配置，其他主机等待 install.sh 分发"""
        all_hosts = self._get_cluster_hosts()
        is_first = self._is_first_host()

        if is_first:
            self.logger.info('[%s@%s] 主节点，执行完整安装流程',
                              self.name, self.ssh.host)
            self._create_dirs()
            self.upload_package()
            self.extract_package()
            self._configure_dolphinscheduler()
            # 在 install.sh 分发前将 HDFS 配置放入 conf 目录，会自动随 install.sh 同步到所有节点
            self._copy_hdfs_configs_to_services()
            self._cleanup_package()
        else:
            self.logger.info('[%s@%s] 非主节点（主节点: %s），仅创建目录',
                              self.name, self.ssh.host, all_hosts[0])
            self._create_dirs()

    def install(self, skip_health_check=False):
        self.logger.info('[%s@%s] === 开始安装 DolphinScheduler ===',
                          self.name, self.ssh.host)
        self.logger.info('[%s@%s] 安装目录: %s，运行用户: %s',
                          self.name, self.ssh.host,
                          self.apps_root, self.ssh.username)

        self.prepare()
        self.start_service()

        if not skip_health_check:
            self.logger.info('[%s@%s] 等待 60 秒后开始健康检查...',
                              self.name, self.ssh.host)
            time.sleep(60)
            self.health_check()

        self.logger.info('[%s@%s] === DolphinScheduler 安装完成 ===',
                          self.name, self.ssh.host)

    def _ds_bin(self, script):
        return os.path.join(self.component_dir, 'bin', script)

    def _ds_env(self):
        return 'export JAVA_HOME={}'.format(shlex.quote(self.java_home))

    def start_service(self):
        if not self._is_first_host():
            self.logger.info('[%s@%s] 非主节点，由主节点 install.sh 统一分发启动',
                              self.name, self.ssh.host)
        else:
            self.logger.info('[%s@%s] 执行 install.sh 部署并启动服务',
                              self.name, self.ssh.host)
            install_sh = self._ds_bin('install.sh')
            cmd = '{} && bash {}'.format(self._ds_env(), shlex.quote(install_sh))
            code, out, err = self.ssh.execute(cmd, timeout=300, check=False)
            if code != 0:
                self.logger.warning('[%s@%s] install.sh 返回码 %d: %s',
                                    self.name, self.ssh.host, code,
                                    (err or out).strip()[:300])
            else:
                self.logger.info('[%s@%s] install.sh 执行完成，服务已启动',
                                  self.name, self.ssh.host)

        # 在所有主机上创建 systemd unit（install.sh 已启动服务，仅 enable 不 start）
        self.logger.info('[%s@%s] 创建 dolphinscheduler systemd unit',
                          self.name, self.ssh.host)
        unit_content = '''[Unit]
Description=DolphinScheduler
After=network.target

[Service]
# start-all.sh 是聚合脚本(启动 master/worker/api/alert 多个进程),forking 无 PIDFile
# 会导致 systemd 判定失败并清理全部进程;必须用 oneshot + RemainAfterExit
Type=oneshot
RemainAfterExit=yes
Environment=JAVA_HOME={java_home}
ExecStart={component_dir}/bin/start-all.sh
ExecStop={component_dir}/bin/stop-all.sh
User=root

[Install]
WantedBy=multi-user.target'''.format(
            java_home=shlex.quote(self.java_home),
            component_dir=shlex.quote(self.component_dir))
        self._create_systemd_unit('dolphinscheduler', unit_content)
        self._enable_systemd_unit('dolphinscheduler', start=False)

    def stop_service(self):
        if not self._is_first_host():
            self.logger.info('[%s@%s] 非主节点，由主节点统一停止服务',
                              self.name, self.ssh.host)
            return
        self.logger.info('[%s@%s] 停止所有 DolphinScheduler 服务',
                          self.name, self.ssh.host)
        stop_all = self._ds_bin('stop-all.sh')
        cmd = '{} && bash {}'.format(self._ds_env(), shlex.quote(stop_all))
        self.ssh.execute(cmd, timeout=60, check=False)
        self.logger.info('[%s@%s] 所有服务已停止', self.name, self.ssh.host)

    def health_check(self):
        if not self._is_first_host():
            self.logger.info('[%s@%s] 非主节点，由主节点统一检查',
                              self.name, self.ssh.host)
            return
        self.logger.info('[%s@%s] 健康检查: 执行 status-all.sh',
                          self.name, self.ssh.host)
        status_sh = self._ds_bin('status-all.sh')
        cmd = '{} && bash {}'.format(self._ds_env(), shlex.quote(status_sh))
        code, out, err = self.ssh.execute(cmd, timeout=30, check=False)
        if code != 0:
            raise RuntimeError(
                '[{}@{}] DolphinScheduler 健康检查失败 (status-all.sh 返回码 {}): {}'
                .format(self.name, self.ssh.host, code, (err or out).strip()[:200]))
        self.logger.info('[%s@%s] DolphinScheduler 健康检查通过\n%s',
                          self.name, self.ssh.host, out.strip())
