# -*- coding: utf-8 -*-
"""健康检查模块 — 供 install.py 和外部工具复用"""
import threading
import time


def run_health_checks(hosts, instances, results, component, lock, config,
                      logger, max_retries=3, retry_interval=60,
                      post_start_delay_seconds=0):
    """在已启动的主机上并行执行健康检查

    Args:
        hosts: list, 待检查的主机列表
        instances: dict, 主机 -> Installer 实例
        results: dict, 组件名 -> {主机: 状态}
        component: str, 组件名称
        lock: threading.Lock, 结果写入锁
        config: DeployConfig namedtuple
        logger: logging.Logger
        max_retries: int, 最大重试次数（默认3）
        retry_interval: int, 重试间隔秒数（默认60）
        post_start_delay_seconds: int, 健康检查前等待秒数（默认0，用于Nacos集群等场景）
    """
    # 前置等待（用于集群场景，等所有节点启动后再统一检查）
    if post_start_delay_seconds > 0:
        started = [h for h in hosts if results[component].get(h) == 'started']
        if started:
            if not config.debug:
                logger.info('--- %s 集群 %d 节点已启动，等待 %d 秒后统一检查 ---',
                            component, len(started), post_start_delay_seconds)
                time.sleep(post_start_delay_seconds)
            else:
                logger.info('--- %s 集群 %d 节点已启动，调试模式跳过 %d 秒等待 ---',
                            component, len(started), post_start_delay_seconds)

    health_threads = []
    for h in hosts:
        if results[component].get(h) != 'started':
            continue
        inst = instances.get(h)
        if not inst:
            continue

        def check_one(hh=h, i=inst):
            for attempt in range(max_retries + 1):
                try:
                    i.health_check()
                    logger.info('[%s] %s 健康检查通过', hh, component)
                    with lock:
                        results[component][hh] = 'success'
                    return
                except Exception as e:
                    if attempt < max_retries:
                        if not config.debug:
                            logger.warning('[%s] %s 健康检查失败（第%d次，共%d次重试），%d秒后重试: %s',
                                           hh, component, attempt + 1, max_retries, retry_interval, e)
                            time.sleep(retry_interval)
                        else:
                            logger.warning('[%s] %s 健康检查失败（第%d次，共%d次重试），调试模式跳过等待: %s',
                                           hh, component, attempt + 1, max_retries, e)
                    else:
                        logger.error('[%s] %s 健康检查重试%d次后仍失败: %s', hh, component, max_retries, e)
                        with lock:
                            results[component][hh] = 'failed'

        t = threading.Thread(target=check_one)
        health_threads.append(t)
        t.start()

    for t in health_threads:
        t.join()