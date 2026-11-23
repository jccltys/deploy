# 统一监控 POC 数据模拟项目

> **使用前必须修改 `config/common_config.yaml`**：将 MySQL 和 Kafka 地址改为实际环境的连接信息，否则程序会连接错误的地址导致失败。
>
> **单独使用**：如果脱离部署引擎独立运行，需要先自行安装 Python 依赖（见 §2），并通过 `--xlsx` 参数手动指定对象实例文件路径。

本套件用于统一监控 POC 环境的数据模拟，支持告警、基础指标、交易指标、链路明细及 ITSM 数据的生成与发送。

## 架构

```
run_mockdata.py          ← 唯一入口，直接 import 调用各模块
  ├── 从 common_config.yaml 读取 Kafka/MySQL 地址
  ├── 支持 --xlsx 指定对象实例 xlsx 文件（默认 lib/odmp/10-aiops-*）
  ├── 一次加载 xlsx 数据，分发给各模块
  ├── 校验时间格式（统一 YYYY-MM-DD HH:MM:SS）
  └── 创建所需 Kafka topic
       │
         ├── tools/getAlert.py           (run 函数)
         ├── tools/getBasicMetrics.py    (run 函数)
         ├── tools/getTransMetrics.py    (run 函数)
         ├── tools/getItsmDevops.py      (run 函数)
         ├── tools/getFixedAlerts.py     (run 函数，固定告警每日循环)
         └── tools/getTransDetails.py    (run 函数)
```

各子脚本通过 `run_mockdata.py` 直接 import 后调用其 `run()` 函数。xlsx 数据只加载一次，所有模块共用。

`run_mockdata.py` 在启动时将自身目录添加到 `sys.path`，使得 `from tools.xxx` 可直接工作。各子脚本保留 `if __name__ == '__main__'` 用于独立调试（不建议直接执行）。

## 1. 项目结构

```text
mockdata/
├── README.md                        # 本说明文档
├── run_mockdata.py                 # 统一启动器（唯一入口）
├── config/
│   ├── basic_metric_type.yaml       # 基础指标类型定义
│   ├── trans_metric.yaml            # 交易指标配置
│   ├── alert_rule_info.csv          # 告警指标与来源定义
│   ├── common_config.yaml           # 公共基础设施配置（MySQL、Kafka 地址）
│   └── trans_details_service.yaml   # 链路服务配置（必选）
├── comms/
│   ├── __init__.py
│   ├── config_loader.py             # 公共配置加载器（topic 默认值、MySQL/Kafka 读取）
│   ├── object_reader.py             # xlsx 对象实例读取模块
│   ├── topic_manager.py             # Kafka topic 管理工具
│   └── logger.py                    # 公共日志模块（日志输出到 logs/）
├── tools/
│   ├── __init__.py
│   ├── getAlert.py                  # 告警数据模拟
│   ├── getBasicMetrics.py           # 基础指标模拟
│   ├── getItsmDevops.py             # ITSM & DevOps 数据模拟
│   ├── getTransDetails.py           # 交易链路明细模拟
│   └── getTransMetrics.py           # 交易指标模拟
```

## 2. 环境要求

- Python 3.6+
- 依赖包位于 `deploy/lib/python/`：
```bash
cd deploy/lib/python/
tar -zxf PyMySQL-1.0.2.tar.gz
cd PyMySQL-1.0.2 && python3 setup.py install && cd ..

tar -zxf kafka-python-2.0.2.tar.gz
cd kafka-python-2.0.2 && python3 setup.py install && cd ..

tar -zxf openpyxl-*.tar.gz
cd openpyxl-* && python3 setup.py install && cd ..

tar -zxf PyYAML-*.tar.gz
cd PyYAML-* && python3 setup.py install && cd ..
```

> 如果使用部署引擎安装，上述依赖默认已安装，无需手动操作。否则需要自行安装，并通过 `--xlsx` 参数指定对象实例文件路径。

## 3. 使用方法

所有模块统一通过 `run_mockdata.py` 启动，在命令后面加上模块标识即可指定运行某个模块。不指定模块标识则运行全部。

### 3.1 多模块组合

可同时指定多个模块标识，按顺序运行。不指定标识则运行全部模块。

```bash
# 运行全部模块
python3 run_mockdata.py

# 全部模块调试模式
python3 run_mockdata.py --debug

# 全部模块指定时间范围
python3 run_mockdata.py --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 告警 + 基础指标
python3 run_mockdata.py alert metrics

# 交易指标 + 链路明细
python3 run_mockdata.py trans-metrics trans-details

# 告警 + 交易指标 + 链路明细（带调试和时间范围）
python3 run_mockdata.py alert trans-metrics trans-details --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 指定对象实例 xlsx 文件（默认自动查找 lib/odmp/10-aiops-objectInstance_*.xlsx）
python3 run_mockdata.py --xlsx /data/softs/job/data/objectInstance.xlsx

# 指定 xlsx + 时间范围 + 特定模块
python3 run_mockdata.py alert metrics --xlsx /data/softs/job/data/objectInstance.xlsx --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

### 3.2 告警数据（alert）

生成告警及告警规则数据，发送到 Kafka。

```bash
# 默认模式（持续循环，每 3 小时生成一批）
python3 run_mockdata.py alert

# 调试模式（不发送 Kafka，仅打印）
python3 run_mockdata.py alert --debug

# 指定时间范围（--start 和 --end 必须同时使用）
python3 run_mockdata.py alert --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 调试 + 时间范围
python3 run_mockdata.py alert --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

### 3.3 基础指标（metrics）

生成基础设施和 APM 指标数据，发送到 Kafka。

```bash
# 默认模式（持续循环，每分钟生成一批）
python3 run_mockdata.py metrics

# 调试模式
python3 run_mockdata.py metrics --debug

# 指定时间范围（--start 和 --end 必须同时使用）
python3 run_mockdata.py metrics --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 调试 + 时间范围
python3 run_mockdata.py metrics --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

#### 异常值配置（基础指标）

在 `config/basic_metric_type.yaml` 对应指标的条目下增加 `default` 平级结构，即可在指定时间段内、对指定对象生成异常值：

```yaml
-
    type: Linux
    metric: CPU使用率
    source: system.cpu.pct_usage
    metricName: 基础监控
    dimension: ""
    default:
      value: 0          # 兜底默认值；省略则未命中回退随机 40-60
      min: 96           # 命中时在 [min, max] 区间随机
      max: 97
      objectIds: ["23u3hkl5m9xf00bk"]   # 可选，限定生效对象
      timeRange:        # 可选，限定生效时间段（HH:MM）
        start: "09:59"
        end: "10:02"
```

规则：`timeRange` 时间段内且 `objectIds` 匹配 → 输出 `[min, max]` 区间随机值；否则输出 `value` 兜底值（`value` 省略时回退随机 40-60）。上例效果：`23u3hkl5m9xf00bk` 的 CPU 使用率在 09:59-10:02 期间一直为 96~97。

### 3.4 交易指标（trans-metrics）

生成交易量、成功率等交易指标数据，发送到 Kafka。

```bash
# 默认模式（持续循环，每分钟生成一批）
python3 run_mockdata.py trans-metrics

# 调试模式
python3 run_mockdata.py trans-metrics --debug

# 指定时间范围（--start 和 --end 必须同时使用）
python3 run_mockdata.py trans-metrics --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 调试 + 时间范围
python3 run_mockdata.py trans-metrics --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

#### 异常值配置（交易指标）

`config/trans_metric.yaml` 的 `cases` 中每个系统含 `baseline`（基线）和 `special`（特殊时段）两段，命中 `special.times` 里的时刻时输出特殊值：

```yaml
  "{object_id_0}":
    baseline:
      - time: "09:59"
        count: 2060
        duration: 0.6
        resp_rate: 98.0
        succ_rate: 97.0
    special:
      - baseline_time: "09:59"
        times: ["10:00", "10:01", "10:02", "10:03", "10:04"]
        count: [1800, 1700, 1680, 1600, 1507]
        duration: [0.8, 0.92, 1.22, 1.33, 1.87]
        resp_rate: [91.0, 90.0, 88.3, 86.2, 85.1]
        succ_rate: [92.0, 91.0, 89.0, 87.2, 86.2]
```

- `times` 与各值数组按下标一一对应；`baseline_time` 必须存在于该系统的 `baseline` 中；
- **仅在奇数天生效**（相对基准日 2025-09-11 的天数差为奇数），偶数天全部走随机正常值；
- 增加/修改：新增或调整 `special`/`baseline` 条目即可，`{object_id_N}` 对应 xlsx 中第 N+1 个业务系统。

### 3.5 交易链路明细（trans-details）

生成银行系统链路交易数据，发送到 Kafka。

```bash
# 默认模式（持续循环，每 0.5 秒生成一批）
python3 run_mockdata.py trans-details

# 调试模式
python3 run_mockdata.py trans-details --debug

# 指定时间范围（--start 和 --end 必须同时使用）
python3 run_mockdata.py trans-details --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 调试 + 时间范围
python3 run_mockdata.py trans-details --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

### 3.6 ITSM 变更单 + DevOps 投产单（itsm-devops）

生成变更工单和投产计划数据，写入 MySQL。

```bash
# 默认模式（持续循环，每 24 小时生成一批）
python3 run_mockdata.py itsm-devops

# 调试模式（不写入数据库，仅打印）
python3 run_mockdata.py itsm-devops --debug

# 指定时间范围（--start 和 --end 必须同时使用）
python3 run_mockdata.py itsm-devops --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

# 调试 + 时间范围
python3 run_mockdata.py itsm-devops --debug --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"
```

### 3.7 固定告警（fixed-alert）

生成 6 条内容固定的告警发送到 Kafka（`alerts_aiops` topic），参考 itsm-devops 的每日循环模式：**启动后立即生成一批，之后每 24 小时生成一批**。

- 告警时间（时分秒毫秒）固定：`10:02:15.000`、`10:04:10.000`、`10:05:40.000`、`10:06:05.000`、`10:07:00.000`、`10:08:20.000`，日期取当天；
- 告警来源分布：2 条「基础监控」、2 条 `apm`、2 条 `bpm`，告警级别均为 5；
- 6 条内容（objectId/metric/alertTitle/alertDescription/ip）固定，alertId 每条随机生成。

```bash
# 通过统一入口常驻运行（启动立即一批，之后每 24h 一批）
python3 run_mockdata.py fixed-alert

# 调试模式（只打印一批后退出）
python3 run_mockdata.py fixed-alert --debug

# 指定日期范围（仅执行一次，日期取 --start 的日期）
python3 run_mockdata.py fixed-alert --start "2026-03-17 00:00:00" --end "2026-03-17 00:10:00"
```

单独运行（不经过统一入口）：

```bash
cd deploy/mockdata

# 常驻运行（启动立即一批，之后每 24h 一批）
nohup python3 tools/getFixedAlerts.py >> logs/fixed_alerts.log 2>&1 &

# 调试模式（只打印不发送）
python3 tools/getFixedAlerts.py --debug

# 指定日期（常驻循环，每天使用该日期）
python3 tools/getFixedAlerts.py --date 2026-09-10
```

> 常驻循环模式与 crontab 调度二选一，不要同时使用，避免每天重复生成。

### 3.8 全局参数

以下参数对所有模块生效：

- `--debug` — 调试模式，不发送/写入数据，仅打印（`python3 run_mockdata.py --debug`）
- `--start` — 开始时间，格式 `YYYY-MM-DD HH:MM:SS`（`--start "2026-03-17 10:00:00"`）
- `--end` — 结束时间，格式 `YYYY-MM-DD HH:MM:SS`（`--end "2026-03-17 10:10:00"`）
- `--xlsx` — xlsx 文件路径，默认 `lib/odmp/10-aiops-objectInstance_*.xlsx`（`--xlsx /path/to/file.xlsx`）

> **重要**：`--start` 和 `--end` **必须同时使用**，不能只指定其中一个。时间格式必须为 `YYYY-MM-DD HH:MM:SS`，缺少任一部分会立即报错。不指定时间参数时，各模块进入持续循环模式（详见各模块说明）。

**模块标识一览：**

- `alert` — 告警数据，发送到 Kafka
- `metrics` — 基础指标，发送到 Kafka
- `trans-metrics` — 交易指标，发送到 Kafka
- `trans-details` — 交易链路明细，发送到 Kafka
- `itsm-devops` — ITSM 变更单 + DevOps 投产单，写入 MySQL
- `fixed-alert` — 固定告警，每天一批（启动立即生成），发送到 Kafka

## 4. 配置说明

### Kafka 地址

Kafka broker 地址从 `config/common_config.yaml` 中的 `kafka.brokers` 读取，不再支持命令行参数指定。

### common_config.yaml

各模块共享的公共基础设施配置文件，必须存在且包含正确的地址：

```yaml
mysql:
  host: 192.168.103.201    # MySQL 地址
  port: 3306               # MySQL 端口
  user: root               # MySQL 用户
  password: "MySQL@123"    # MySQL 密码

kafka:
  brokers: "host1:9092,host2:9092"   # Kafka broker 列表
```

配置文件不存在或缺少必要字段时，程序会给出明确提示并要求填写。

### trans_details_service.yaml

交易链路明细的配置文件，**必须存在**。缺失时 `getTransDetails.py` 会报错退出，不会自动生成默认配置。

> **关于模板变量**：`trans_metric.yaml` 和 `trans_details_service.yaml` 支持 `{object_id_0}`、`{object_name_0}` 等占位符，运行时根据 xlsx 加载的对象实例自动替换。替换在**内存中完成，不会修改原文件**。如果配置中没有占位符，则作为静态配置直接使用，无需任何特殊处理。

### topic 名称

Topic 名称使用 `comms/config_loader.py` 中的内置默认值，无需在配置文件中定义：

- **告警数据** — `alerts_aiops`
- **告警规则** — `alerts_rule_aiops`
- **告警 unialert** — `alerts_aiops_unialert`
- **基础指标-基础设施** — `infra_metrics_aiops`
- **基础指标-APM** — `apm_metrics_aiops`
- **交易指标** — `bpm_trans_metrics_aiops`
- **交易链路明细** — `bpm_trans_details_aiops`

#### 手动创建 topic

统一入口只会自动创建告警相关的 3 个 topic（`alerts_aiops`、`alerts_rule_aiops`、`alerts_aiops_unialert`）；`infra_metrics_aiops`、`apm_metrics_aiops`、`bpm_trans_metrics_aiops`、`bpm_trans_details_aiops` 这 4 个依赖 Kafka 服务端 `auto.create.topics.enable=true` 兜底自动创建。若生产环境关闭了该开关，需手动创建全部 7 个 topic（在任一 Kafka 节点执行，`KAFKA_BIN` 与 `BROKER` 按实际环境替换）：

```bash
KAFKA_BIN={install-dir}/comms/kafka/bin/kafka-topics.sh
BROKER="<kafka1>:9092,<kafka2>:9092,<kafka3>:9092"

$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic alerts_aiops --partitions 3 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic alerts_rule_aiops --partitions 3 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic alerts_aiops_unialert --partitions 1 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic rizhi_alerts_unialert --partitions 1 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic infra_metrics_aiops --partitions 3 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic apm_metrics_aiops --partitions 3 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic bpm_trans_metrics_aiops --partitions 3 --replication-factor 1
$KAFKA_BIN --bootstrap-server $BROKER --create --if-not-exists --topic bpm_trans_details_aiops --partitions 3 --replication-factor 1
```

验证创建结果：

```bash
$KAFKA_BIN --bootstrap-server $BROKER --list | grep aiops
```

> 分区数与工具 `ensure_topics` 的行为一致；`--replication-factor 1` 与工具一致，生产高可用环境可改为 2 或 3（需注意与工具自动创建的 3 个 alert topic 保持一致策略）。`--if-not-exists` 保证重复执行幂等。

### 使用前准备

1. 确保 `deploy/lib/odmp/` 下存在 `10-aiops-objectInstance_*.xlsx` 文件，或通过 `--xlsx` 指定路径
2. 确保 `config/common_config.yaml` 中 MySQL 和 Kafka 地址配置正确
3. `alerts_aiops`、`alerts_rule_aiops` 等 topic 会自动创建（需要 Kafka 可访问）
