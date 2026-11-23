# -*- coding: utf-8 -*-
"""业务应用组件健康检查器"""
import os
import shlex

from core.config_utils import (
    get_component_config,
    get_sso_vars,
    get_odmp_vars,
    get_refiner_vars,
    get_aimeter_vars,
)
from tools.nacos_api import NacosConfigManager
from .health_base import HealthChecker, check_port


class SsoChecker(HealthChecker):
    """SSO 健康检查器 — 端口检查 + Nacos 服务注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        sso_cfg = get_component_config(self.config, 'sso')
        auth_port = sso_cfg.get('authentication_port', 9912)
        gw_port = sso_cfg.get('gateway_port', 8080)

        # 1. Port check
        for port, label in [(auth_port, 'authentication'), (gw_port, 'gateway')]:
            check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
            if self.logger:
                self.logger.info('[health] SSO %s 端口 %d 监听正常', label, port)

        # 2. Nacos service registration check
        sso_vars = get_sso_vars(self.context, self.config) if self.context else None
        if not sso_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = sso_vars['nacos_host']
        nacos_user = sso_vars['nacos_user']
        nacos_password = sso_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('authentication', 'gateway'):
            mgr.check_service_registration(
                nacos_host, service_name, token, ssh=self.ssh)
            if self.logger:
                self.logger.info(
                    '[health] SSO %s Nacos 注册检查通过', service_name)

        return True


class OdmpChecker(HealthChecker):
    """ODMP 健康检查器 — 端口检查 + Nacos 服务注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        odmp_cfg = get_component_config(self.config, 'odmp')
        port = odmp_cfg.get('port', 9900)

        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] ODMP 端口 %d 监听正常', port)

        odmp_vars = get_odmp_vars(self.context, self.config) if self.context else None
        if not odmp_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = odmp_vars['nacos_host']
        nacos_user = odmp_vars['nacos_user']
        nacos_password = odmp_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)

        for service_name in ('odmp',):
            mgr.check_service_registration(
                nacos_host, service_name, token, ssh=self.ssh)
            if self.logger:
                self.logger.info(
                    '[health] ODMP Nacos 注册检查通过')

        return True


class RefinerProChecker(HealthChecker):
    """REFINER PRO 子服务健康检查器 — 端口检查 + Nacos 注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        refiner_cfg = get_component_config(self.config, 'refiner')
        port = refiner_cfg.get('refiner_pro_port', 9091)

        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] REFINER refiner-pro 端口 %d 监听正常', port)

        refiner_vars = get_refiner_vars(self.context, self.config) if self.context else None
        if not refiner_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = refiner_vars['nacos_host']
        nacos_user = refiner_vars['nacos_user']
        nacos_password = refiner_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)
        mgr.check_service_registration(nacos_host, 'refiner', token, ssh=self.ssh)
        if self.logger:
            self.logger.info('[health] REFINER refiner Nacos 注册检查通过')
        return True


class RefinerEtlChecker(HealthChecker):
    """REFINER ETL 子服务健康检查器 — 端口检查 + Nacos 注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        refiner_cfg = get_component_config(self.config, 'refiner')
        port = refiner_cfg.get('refiner_etl_port', 19091)

        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] REFINER refiner-pro-etl 端口 %d 监听正常', port)

        refiner_vars = get_refiner_vars(self.context, self.config) if self.context else None
        if not refiner_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = refiner_vars['nacos_host']
        nacos_user = refiner_vars['nacos_user']
        nacos_password = refiner_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)
        mgr.check_service_registration(nacos_host, 'refiner-etl', token, ssh=self.ssh)
        if self.logger:
            self.logger.info('[health] REFINER refiner-etl Nacos 注册检查通过')
        return True


class AimeterAlertChecker(HealthChecker):
    """AIMETER alert 子服务健康检查器 — 端口检查 + Nacos 注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        aimeter_cfg = get_component_config(self.config, 'aimeter')
        port = aimeter_cfg.get('alert_port', 36888)

        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] AIMETER aimeter 端口 %d 监听正常', port)

        aimeter_vars = get_aimeter_vars(self.context, self.config) if self.context else None
        if not aimeter_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = aimeter_vars['nacos_host']
        nacos_user = aimeter_vars['nacos_user']
        nacos_password = aimeter_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)
        mgr.check_service_registration(nacos_host, 'aimeter', token, ssh=self.ssh)
        if self.logger:
            self.logger.info('[health] AIMETER aimeter Nacos 注册检查通过')
        return True


class AimeterSchedulerChecker(HealthChecker):
    """AIMETER scheduler 子服务健康检查器 — 端口检查 + Nacos 注册检查"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        aimeter_cfg = get_component_config(self.config, 'aimeter')
        port = aimeter_cfg.get('alert_sch_port', 36889)

        check_port(self.ssh, self.ssh.host, port, timeout=30, logger=self.logger)
        if self.logger:
            self.logger.info('[health] AIMETER aimeter-scheduler 端口 %d 监听正常', port)

        aimeter_vars = get_aimeter_vars(self.context, self.config) if self.context else None
        if not aimeter_vars:
            if self.logger:
                self.logger.warning('[health] 无上下文信息，跳过 Nacos 注册检查')
            return True

        nacos_host = aimeter_vars['nacos_host']
        nacos_user = aimeter_vars['nacos_user']
        nacos_password = aimeter_vars['nacos_password']

        mgr = NacosConfigManager(logger=self.logger)
        token = mgr.login(nacos_host, nacos_user, nacos_password, ssh=self.ssh)
        mgr.check_service_registration(nacos_host, 'aimeter-scheduler', token, ssh=self.ssh)
        if self.logger:
            self.logger.info('[health] AIMETER aimeter-scheduler Nacos 注册检查通过')
        return True


class DolphinschedulerChecker(HealthChecker):
    """DolphinScheduler 健康检查器 — 通过 status-all.sh 检查各服务进程"""

    def __init__(self, ssh_client, component_dir, config=None, logger=None,
                 context=None):
        super().__init__(ssh_client, component_dir, config, logger)
        self.context = context

    def check(self):
        status_sh = os.path.join(self.component_dir, 'bin', 'status-all.sh')
        cmd = 'bash {} 2>&1'.format(shlex.quote(status_sh))
        if self.logger:
            self.logger.info('[health] 执行: %s', cmd)
        code, out, err = self.ssh.execute(cmd, timeout=30, check=False)
        if self.logger:
            self.logger.info('[health] status-all.sh 返回码: %d', code)
            self.logger.info('[health] status-all.sh 输出:\n%s', out.strip())

        if code != 0:
            raise RuntimeError(
                'DolphinScheduler 服务异常 (返回码 {}): {}'
                .format(code, (err or out).strip()[:200]))

        expected = ['MasterServer', 'WorkerServer', 'ApiServer', 'AlertServer']
        running = [s for s in expected if s.lower() in out.lower()]
        if len(running) < len(expected):
            missing = [s for s in expected if s not in running]
            self.logger.warning('[health] 部分服务未运行: %s', ', '.join(missing))

        if self.logger:
            self.logger.info('[health] DolphinScheduler 健康检查通过')
        return True
