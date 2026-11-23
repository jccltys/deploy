# 配置模板变量参考（自动生成）

## aimeter

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## ckman

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## clickhouse

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## hadoop

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${jnode_hosts}` | str | JournalNode 地址列表（分号分隔） | 所有 hadoop 主机 | node1:8485;node2:8485;node3:8485 |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${nn1_host}` | str | 主 NameNode 主机名 | deploy 映射中第一个 hadoop 主机 | - |
| `${nn2_host}` | str | 备用 NameNode 主机名 | deploy 映射中第二个 hadoop 主机（如存在） | - |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |
| `${rm1_host}` | str | 主 ResourceManager 主机名 | 同 nn1_host | - |
| `${rm2_host}` | str | 备用 ResourceManager 主机名 | 同 nn2_host | - |
| `${rm_id}` | str | 当前主机的 RM 角色 ID | 自动分配（rm1 或 rm2） | rm1 |
| `${zk_quorum}` | str | ZooKeeper 仲裁地址列表 | 自动从 deploy 映射推导 | node1:2181,node2:2181,node3:2181 |

## java

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## java11

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## java21

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## kafka

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${broker_id}` | str | Kafka broker ID | 自动分配（按主机名排序 0, 1, 2...） | 0 |
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |
| `${zookeeper_connect}` | str | ZooKeeper 连接串 | 自动从 deploy 映射推导 | node1:2181,node2:2181,node3:2181 |

## mysql

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## nacos

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${nacos_servers}` | str | Nacos 集群节点配置（每行一个 IP） | 自动从 deploy 映射推导（节点数=3时生成） | 192.168.1.2:8848
192.168.1.3:8848
192.168.1.4:8848 |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## nebula

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## nebula_studio

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## nginx

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${aimeter_ip}` | str | aimeter 服务 IP | 从 deploy 中查找含 aimeter 的主机 | - |
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${frontend_dir}` | str | 前端静态文件目录 | 自动计算 | /data/service/apps/odc/app_frontend/dist |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${local_ip}` | str | 当前主机 IP | config.servers 中的主机地址 | - |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${nginx_listen_port}` | str | Nginx 监听端口 | config.yaml nginx.listen_port | 10082 |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |
| `${odc_ip}` | str | ODC 服务 IP | 从 deploy 中查找含 odc 的主机 | - |
| `${refiner_ip}` | str | refiner 服务 IP | 从 deploy 中查找含 refiner 的主机 | - |
| `${sso_ip}` | str | 认证服务 IP | 从 deploy 中查找含 sso 的主机 | - |

## odc

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## odmp

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## redis

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## refiner

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## sso

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |

## zookeeper

| 变量 | 类型 | 说明 | 来源 | 示例 |
|------|------|------|------|------|
| `${comms_dir}` | str | 远程软件解压/安装目录 | 自动计算（install_dir/comms） | /data/service/comms |
| `${component_dir}` | str | 组件软链接路径（comms/{name}） | 自动计算 | /data/service/comms/redis |
| `${data_dir}` | str | 组件数据目录 | 自动计算（component_dir/data） | /data/service/comms/redis/data |
| `${host_ip}` | str | 部署机 IP（目标主机下载安装包用） | CLI 参数 --localaddr | 192.168.1.100 |
| `${install_dir}` | str | 安装根目录 | CLI 参数 --install-dir | /data/service |
| `${java_home}` | str | 默认 JDK 路径（JDK 8 软链接） | 自动计算（comms_dir/java） | /data/service/comms/java |
| `${log_dir}` | str | 组件日志目录 | 自动计算（component_dir/logs） | /data/service/comms/redis/logs |
| `${myid}` | str | 当前主机的 Zookeeper 节点 ID | 自动分配（1, 2, 3...） | 1 |
| `${node_ip}` | str | 当前目标主机 IP | config.yaml servers 中的 host | 192.168.1.2 |
| `${zk_servers}` | str | Zookeeper 集群节点配置（server.1, server.2, server.3） | 自动从 deploy 映射推导（节点数>2时使用前3个IP） | server.1=192.168.1.2:2888:3888\nserver.2=192.168.1.3:2888:3888\nserver.3=192.168.1.4:2888:3888 |
