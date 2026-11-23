# -*- coding: utf-8 -*-
"""
部署编排模块 — 组件的部署调度（分阶段 / 并行 / 集群分派）

从 install.py 拆分而来，供主流程调用：deploy_component / prepare_all_hosts。
"""
import threading

from core.ssh_client import get_ssh_client
from core.health_check import run_health_checks


def _parallel_for_each(hosts, worker_fn):
    """在每台主机上并行执行 worker_fn(host)，等待全部完成"""
    threads = [threading.Thread(target=worker_fn, args=(h,)) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _deploy_legacy_mode(hosts, installer_cls, servers_map, config, context, logger, results, component):
    """传统部署模式：并行 install()，适合 Hadoop 等需要整体初始化流程的组件"""
    logger.info('[%s] Phase 1: 并行安装', component)
    _instances = {}
    lock = threading.Lock()

    def _install_one(host):
        server_info = servers_map.get(host)
        if not server_info:
            logger.error('未找到主机 %s 的 SSH 配置', host)
            with lock:
                results[component][host] = 'skipped'
            return
        ssh = get_ssh_client(server_info, dry_run=config.debug, logger=logger)
        try:
            inst = installer_cls(ssh, config, context, logger)
            inst.install(skip_health_check=True)
            with lock:
                _instances[host] = inst
                results[component][host] = 'started'
        except Exception as e:
            logger.error('[%s@%s] 安装失败: %s', component, host, e)
            with lock:
                results[component][host] = 'failed'

    _parallel_for_each(hosts, _install_one)
    return _instances, lock


def _deploy_phased_mode(hosts, installer_cls, servers_map, config, context, logger, results, component):
    """分阶段部署模式：先并行准备，再并行启动，最后统一健康检查"""
    _instances = {}
    lock = threading.Lock()

    # Phase 1: 所有主机并行准备
    logger.info('[%s] Phase 1: 并行准备', component)
    def _prepare_one(host):
        server_info = servers_map.get(host)
        if not server_info:
            logger.error('未找到主机 %s 的 SSH 配置', host)
            with lock:
                results[component][host] = 'skipped'
            return
        ssh = get_ssh_client(server_info, dry_run=config.debug, logger=logger)
        try:
            inst = installer_cls(ssh, config, context, logger)
            inst.prepare()
            with lock:
                _instances[host] = inst
                results[component][host] = 'prepared'
        except Exception as e:
            logger.error('[%s@%s] 准备阶段失败: %s', component, host, e)
            with lock:
                results[component][host] = 'failed'

    _parallel_for_each(hosts, _prepare_one)

    failed_prep = [h for h in hosts if results[component].get(h) == 'failed']
    if failed_prep and config.fail_fast:
        logger.error('===== %s 部署因准备阶段失败中止: %s =====', component, ', '.join(failed_prep))
        return _instances, lock

    # Phase 2: 所有主机并行启动
    logger.info('[%s] Phase 2: 并行启动', component)
    def _start_one(host):
        if results[component].get(host) == 'failed':
            return
        inst = _instances.get(host)
        if not inst:
            return
        try:
            inst.start_service()
            with lock:
                results[component][host] = 'started'
        except Exception as e:
            logger.error('[%s@%s] 启动失败: %s', component, host, e)
            with lock:
                results[component][host] = 'failed'

    _parallel_for_each(hosts, _start_one)
    return _instances, lock


def _deploy_multi_host(hosts, installer_cls, servers_map, config, context, logger, results, component,
                       use_install=False):
    """多主机组件通用分阶段部署

    默认方式（use_install=False）：先并行准备，再并行启动，最后统一健康检查。
    传统方式（use_install=True）：直接并行 install()，再统一健康检查（如 Hadoop）。
    """
    logger.info('--- %s 多主机分阶段部署，目标主机: %s ---', component, ', '.join(hosts))
    results.setdefault(component, {})
    retry_interval = 60 if getattr(installer_cls, 'GROUP', '') == 'common' else 120

    if use_install:
        _instances, lock = _deploy_legacy_mode(hosts, installer_cls, servers_map, config, context, logger, results, component)
    else:
        _instances, lock = _deploy_phased_mode(hosts, installer_cls, servers_map, config, context, logger, results, component)

    # 最后阶段：所有主机启动完成后统一健康检查
    run_health_checks(hosts, _instances, results, component, lock, config, logger,
                      max_retries=6, retry_interval=retry_interval)

    for host in hosts:
        inst = _instances.get(host)
        if inst:
            inst.ssh.close()

    failed = [h for h, s in results[component].items() if s == 'failed']
    if failed:
        logger.warning('--- 组件 %s 在以下主机安装失败: %s ---', component, ', '.join(failed))
    else:
        logger.info('--- 组件 %s 部署完毕（%d 台主机）---', component, len(hosts))

    return _instances


def deploy_component(component, hosts, registry, servers_map, config, context, logger, results):
    """在指定组件的所有目标主机上部署"""
    installer_cls = registry.get(component)
    if not installer_cls:
        logger.warning('未找到组件安装器: %s', component)
        return

    # cluster 模式：组件自带集群入口（nacos / clickhouse）
    if installer_cls.DEPLOY_MODE == 'cluster':
        installer_cls.deploy_cluster(hosts, servers_map, config, context, logger, results)
        return

    # legacy 模式：并行 install（hadoop）
    use_install = (installer_cls.DEPLOY_MODE == 'legacy')

    # 多主机 vs 单主机
    is_multi = len(hosts) > 1
    if is_multi:
        _instances = _deploy_multi_host(hosts, installer_cls, servers_map, config, context, logger, results, component,
                                        use_install=use_install)
    else:
        # 单主机：直接安装 + 健康检查
        logger.info('--- 开始部署 %s ---', component)
        results.setdefault(component, {})
        lock = threading.Lock()

        def _get_ssh(h):
            server_info = servers_map.get(h)
            if not server_info:
                logger.error('未找到主机 %s 的 SSH 配置', h)
                results[component][h] = 'skipped'
                return None
            return get_ssh_client(server_info, dry_run=config.debug, logger=logger)

        host = hosts[0]
        ssh = _get_ssh(host)
        _instances = {}
        if ssh:
            try:
                inst = installer_cls(ssh, config, context, logger)
                inst.install(skip_health_check=True)
                _instances = {host: inst}
                results[component][host] = 'started'
            except Exception as e:
                logger.error('[%s@%s] 安装失败: %s', component, host, e)
                results[component][host] = 'failed'

        run_health_checks(hosts, _instances, results, component, lock, config, logger,
                          max_retries=6, retry_interval=60)

        if ssh:
            ssh.close()

    # 后置初始化：健康检查通过后执行（组件按需覆盖 post_deploy）
    failed = [h for h, s in results[component].items() if s == 'failed']
    installer_cls.post_deploy(hosts, _instances, servers_map, config, context, logger, results, failed)

    failed = [h for h, s in results[component].items() if s == 'failed']
    if failed:
        logger.warning('--- 组件 %s 安装失败 ---', component)
    else:
        logger.info('--- 组件 %s 部署完毕 ---', component)


def prepare_all_hosts(deploy_map, servers_map, config, context, logger):
    """在每台主机上并行创建公共目录（install_dir、comms、apps）"""
    all_hosts = set(deploy_map.keys())
    logger.info('--- 初始化 %d 台主机的公共目录 ---', len(all_hosts))
    threads = []
    for host in all_hosts:
        server_info = servers_map.get(host)
        if not server_info:
            logger.warning('跳过主机 %s：未找到 SSH 配置', host)
            continue

        def prepare_one(h=host, si=server_info):
            dry_run = config.debug
            ssh = get_ssh_client(si, dry_run=dry_run, logger=logger)
            dirs = [config.install_dir, config.comms_dir, config.apps_dir]
            for d in dirs:
                ssh.execute('mkdir -p ' + d)
                logger.debug('[%s] 确认目录: %s', h, d)

        t = threading.Thread(target=prepare_one)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
