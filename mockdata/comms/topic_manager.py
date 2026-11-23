# -*- coding: utf-8 -*-
"""
Kafka topic 管理工具

提供 topic 创建/检查的基础方法，供各 mock 数据脚本及统一启动器调用。
"""
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

from comms.logger import topic_logger as logger


def ensure_topics(broker, topic_defs, client_id='mockdata_admin'):
    """确保 Kafka topic 存在，不存在则创建（不阻塞后续流程）

    Args:
        broker: Kafka bootstrap servers 地址
        topic_defs: [(topic_name, num_partitions), ...]
        client_id: KafkaAdminClient client ID
    """
    if not broker:
        return
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=broker,
            client_id=client_id,
        )
        existing_topics = set(admin_client.list_topics())
        new_topics = []
        for topic_name, num_partitions in topic_defs:
            if topic_name not in existing_topics:
                new_topics.append(NewTopic(
                    name=topic_name,
                    num_partitions=num_partitions,
                    replication_factor=1,
                ))
        if new_topics:
            admin_client.create_topics(new_topics)
            logger.info('已创建 topic: %s', [t.name for t in new_topics])
        admin_client.close()
    except TopicAlreadyExistsError:
        pass
    except Exception as e:
        logger.warning('Topic 创建/检查失败 (不影响后续): %s', e)
