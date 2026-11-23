# -*- coding: utf-8 -*-
"""
Java（JDK 8 默认）安装器
安装到 {comms}/java，配置 JAVA_HOME 环境变量
"""
import os
import shlex

from installers.common.base_installer import BaseInstaller


class JavaInstaller(BaseInstaller):
    GROUP = 'common'
    @property
    def component_dir(self):
        return os.path.join(self.comms_dir, 'java')

    def _create_dirs(self):
        self.logger.debug('[%s@%s] 创建目录: %s',
                          self.name, self.ssh.host, self.comms_dir)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.comms_dir)))

    def extract_package(self):
        """解压 JDK 并创建 java 软链接"""
        self.logger.info('[%s@%s] 正在解压 JDK', self.name, self.ssh.host)
        self.ssh.execute('mkdir -p {}'.format(shlex.quote(self.comms_dir)))

        extract_cmd_tpl, extracted_basename = self._archive_ext(self.package_file)

        # 调试模式：跳过实际解压，从包名推导目录名
        if self.ssh.dry_run:
            java_home = os.path.join(self.comms_dir, extracted_basename)
            symlink = self.component_dir
            self.ssh.execute('ln -snf {} {}'.format(
                shlex.quote(extracted_basename), shlex.quote(symlink)))
            self._java_home = java_home
            self.logger.info('[%s@%s] (调试模式) JDK 模拟解压到 %s，软链接 %s -> %s',
                              self.name, self.ssh.host, java_home, symlink, extracted_basename)
            return

        comms_q = shlex.quote(self.comms_dir)
        code, before, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(comms_q))
        before_set = set(before.strip().split('\n')) if before.strip() else set()

        # 按归档格式解压到 comms 目录
        pkg_q = shlex.quote(self._pkg_path)
        cmd = extract_cmd_tpl.format(pkg=pkg_q, dir=comms_q)
        code, out, err = self.ssh.execute(cmd)
        if code != 0:
            cmd = 'tar -xzf {} -C {}'.format(pkg_q, comms_q)
            code, out, err = self.ssh.execute(cmd)
        if code != 0:
            cmd = 'tar -xJf {} -C {}'.format(pkg_q, comms_q)
            code, out, err = self.ssh.execute(cmd)
        if code != 0:
            raise RuntimeError('[{}@{}] JDK 解压失败: {}'.format(self.name, self.ssh.host, err))

        # 找出解压产生的新目录
        code, after, _ = self.ssh.execute(
            'ls -1A {}/ 2>/dev/null'.format(comms_q))
        after_set = set(after.strip().split('\n')) if after.strip() else set()
        new_entries = after_set - before_set
        new_dirs = [e for e in new_entries if e]
        if not new_dirs:
            raise RuntimeError('[{}@{}] JDK 解压后未发现新目录'.format(self.name, self.ssh.host))
        extracted_basename = sorted(new_dirs)[0].rstrip('/')

        # 创建软链接 comms/java -> {实际版本目录}
        java_home = os.path.join(self.comms_dir, extracted_basename)
        symlink = self.component_dir
        self.ssh.execute('ln -snf {} {}'.format(
            shlex.quote(extracted_basename), shlex.quote(symlink)))
        self._java_home = java_home
        self.logger.info('[%s@%s] JDK 安装到 %s，软链接 %s -> %s',
                         self.name, self.ssh.host, java_home, symlink, extracted_basename)

    def render_configs(self):
        """配置 JAVA_HOME 等环境变量到 ~/.bashrc，使用软链接路径"""
        java_home = self.component_dir  # 使用软链接（如 /data/comms/java），不写死版本目录
        self.logger.info('[%s@%s] 配置 JAVA_HOME: %s', self.name, self.ssh.host, java_home)

        marker = '#deploy_java_home'
        home_q = shlex.quote(java_home)
        cmds = (
            'grep -qF "{m}" ~/.bashrc 2>/dev/null || cat >> ~/.bashrc << \'EOF\'\n'
            '{m}\n'
            'export JAVA_HOME={h}\n'
            'export JRE_HOME=$JAVA_HOME/jre\n'
            'export CLASSPATH=.:$CLASSPATH:$JAVA_HOME/jre/lib\n'
            'export PATH=$JAVA_HOME/bin:$PATH\n'
            'EOF'
        ).format(m=marker, h=home_q)
        self.ssh.execute(cmds)
        self.ssh.execute('source ~/.bashrc')

    def start_service(self):
        self.logger.info('[%s@%s] JDK 无需启动服务', self.name, self.ssh.host)

    def install(self, skip_health_check=False):
        """Java 安装流程：健康检查通过后再清理安装包"""
        self.logger.info('[%s@%s] === 开始安装 ===', self.name, self.ssh.host)
        self._create_dirs()
        self.upload_package()
        self.extract_package()
        self._create_data_dirs()
        self._rendered_files = []
        self.render_configs()
        self._save_config_snapshot()
        self.start_service()
        if not skip_health_check:
            self.health_check()
        self._cleanup_package()
        self.logger.info('[%s@%s] === 安装完成 ===', self.name, self.ssh.host)
