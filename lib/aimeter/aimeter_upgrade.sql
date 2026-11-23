INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES('1485332896571394','business_scene','business_scene_threshold_config','{\n  "enable": true,\n  "rules": [\n    {\n      "start": 0,\n      "end": 800,\n      "color": "#2D7CFA"\n    },\n    {\n      "start": 800,\n      "end": 1000,\n      "color": "#e6a23c"\n    },\n    {\n      "start": 1000,\n      "end": null,\n      "color": "#f56c6c"\n    }\n  ]\n}','',NULL,'20200321','1717744762712',NULL,'20200321','1720602091361','json');
INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES('1516014082284545','transaction-link','transTimeStatusEnable','true','交易链路的交易状态阈值配置，当交易失败时标记为红色',NULL,'20200321','1718681078194',NULL,'20200321','1718681078194','json');
INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES('1516014082284545','transaction-link','transTimeStatusEnable','true','交易链路的交易状态阈值配置，当交易失败时标记为红色',NULL,'20200321','1718681078194',NULL,'20200321','1718681078194','json');

INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES('1559306737354754','metric_export','metric_export_config','{\n  "singleFileSize": 10,\n  "maxFiles": 20,\n  "remark": "singleFileSize表示单个文件大小，单位MB，超出则截断；maxFiles表示导出最多允许的指标实例数，每个指标实例导出一个文件，超出的则舍弃。"\n}','指标导出配置',NULL,'20200321','1720002265179',NULL,'20200321','1720002265179','json');

INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1722965978531841, 'business_scene', 'business_scene_dynamic_threshold_config', '{  "enable": true,  "queryRange": 7,  "combinedStandardDefaultValue": 10,  "rules": [    {      "start": 0,      "end": 2,      "color": "#2D7CFA"    },    {      "start": 2,      "end": 3,      "color": "#e6a23c"    },    {      "start": 3,      "end": null,      "color": "#f56c6c"    }  ]}', '使用动态基线方式识别全链路日志交易响应时间的异常情况，如果动态基线和静态阈值参数同时生效，则优先静态阈值。', NULL, 20200321, 1724996748858, NULL, 20200321, 1725013994123, 'json');
UPDATE tb_dict SET value='{"enable": false,"rules": [{"start": 0,"end": 800,"color": "#2D7CFA"},{"start": 800,"end": 1000,"color": "#e6a23c"},{"start": 1000,"end": null,"color": "#f56c6c"}]}' WHERE id = 1485332896571394;
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1731935276154881, 'transaction-link', 'agg_indicator', '[{"value": "count","label": "请求数"},{"value": "errorCount","label": "系统错误数"},{"value": "slowCount","label": "慢请求数"},{"value": "errorRate","label": "系统错误率"},{"value": "successRate","label": "系统成功率"},{"value": "transCode","label": "交易码"},{"value": "avgDuration","label": "平均耗时(ms)"}]', 'value值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725270470097, NULL, 20200321, 1725271825623, 'json');
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1731973640175618, 'transaction-link', 'single_series_indicator', '[{"value": "startTime","label": "开始时间"},{"value": "endTime","label": "结束时间"},{"value": "reqTime","label": "请求时间"},{"value": "respTime","label": "响应时间"},{"value": "duration","label": "响应耗时(ms)"},{"value": "tranStatus","label": "交易状态"},{"value": "systemCode","label": "业务系统"},{"value": "serviceName","label": "业务服务"},{"value": "transCode","label": "交易码"},{"value": "transCodeName","label": "交易码名称"},{"value": "retCode","label": "交易返回码"}]', 'value值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725271640874, NULL, 20200321, 1725271664531, 'json');
INSERT INTO tb_base_menu (menu_id,menu_name,parent_id,service_name,`path`,menu_key,menu_type,menu_category,menu_sort,route,`method`,remark,icon,is_request,is_home,status,created,created_by,updated,updated_by) VALUES
    (1109282693036643,'首页',1118149469626864,'aimeter','overview','overview','page','leftMenu',1,NULL,'',NULL,'icon-description-line',0,1,0,1725355853046,20200321,1725413586340,20200321);
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES (1731498244587521, 'log_scene_analysis', 'log_scene_analysis_metric', '[{"label": "请求数","key": "count"},{"label": "系统错误率","key": "errorRate"},{"label": "系统错误数","key": "errorCount"},{"label": "平均响应时间","key": "avgDuration"},{"label": "关联告警数","key": "alertCount"}]', 'key值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725257132952, NULL, 5405847568024576, 1725434272023, 'json');
UPDATE tb_dict SET value='{
  "enable": true,
  "queryRange": 7,
  "combinedStandardDefaultValue": 10,
  "meanPercentage": 1.3,
  "rules": [
    {
      "start": 0,
      "end": 2,
      "color": "#2D7CFA"
    },
    {
      "start": 2,
      "end": 3,
      "color": "#e6a23c"
    },
    {
      "start": 3,
      "end": null,
      "color": "#f56c6c"
    }
  ]
}' WHERE id = 1722965978531841;
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750926726674433,'transaction-link','analysis_link_mode','graph','交易链追踪-交易链路的默认展示模式
可选值：graph 或 table（其余无效值会被初始化为graph）',NULL,20200321,1725850043172,NULL,20200321,1725868228631,'text');
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750910204917761,'transaction-link','spl_field_query_logic','OR','跳转日志详情时spl语句的字段查询逻辑
可选值：OR 或 AND （其余无效值会被初始化为 OR）',NULL,20200321,1725849538968,NULL,20200321,1725868220460,'text');
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750832863459329,'transaction-link','x6_graph_config','{
  "virtual": false
}','交易链路x6图表的全局配置',NULL,20200321,1725847178695,NULL,20200321,1725946131669,'json');
UPDATE tb_dict SET `value` = REPLACE(`value`, '\n', '') WHERE `data_group`='business_scene' AND `name`='business_scene_threshold_config';

INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2119668958166017, 'transaction-link', 'trans_analysis_page_time_filter', '["now-10m","now"]', '', NULL, 20200321, 1737103163029, NULL, 20200321, 1737103565766, 'json');

INSERT INTO tb_dict
(id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES(1842235715378178, 'log-search', 'stream_search_config', '{
  "singleQueryMaxCount": 100,
  "chunkDurationMinutes": 5
}', '', NULL, 20200321, 1728636572368, NULL, 20200321, 1728715955616, 'json');

INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1722965978531841, 'business_scene', 'business_scene_dynamic_threshold_config', '{  "enable": true,  "queryRange": 7,  "combinedStandardDefaultValue": 10,  "rules": [    {      "start": 0,      "end": 2,      "color": "#2D7CFA"    },    {      "start": 2,      "end": 3,      "color": "#e6a23c"    },    {      "start": 3,      "end": null,      "color": "#f56c6c"    }  ]}', '使用动态基线方式识别全链路日志交易响应时间的异常情况，如果动态基线和静态阈值参数同时生效，则优先静态阈值。', NULL, 20200321, 1724996748858, NULL, 20200321, 1725013994123, 'json');
UPDATE tb_dict SET value='{"enable": false,"rules": [{"start": 0,"end": 800,"color": "#2D7CFA"},{"start": 800,"end": 1000,"color": "#e6a23c"},{"start": 1000,"end": null,"color": "#f56c6c"}]}' WHERE id = 1485332896571394;
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1731935276154881, 'transaction-link', 'agg_indicator', '[{"value": "count","label": "请求数"},{"value": "errorCount","label": "系统错误数"},{"value": "slowCount","label": "慢请求数"},{"value": "errorRate","label": "系统错误率"},{"value": "successRate","label": "系统成功率"},{"value": "transCode","label": "交易码"},{"value": "avgDuration","label": "平均耗时(ms)"}]', 'value值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725270470097, NULL, 20200321, 1725271825623, 'json');
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES (1731973640175618, 'transaction-link', 'single_series_indicator', '[{"value": "startTime","label": "开始时间"},{"value": "endTime","label": "结束时间"},{"value": "reqTime","label": "请求时间"},{"value": "respTime","label": "响应时间"},{"value": "duration","label": "响应耗时(ms)"},{"value": "tranStatus","label": "交易状态"},{"value": "systemCode","label": "业务系统"},{"value": "serviceName","label": "业务服务"},{"value": "transCode","label": "交易码"},{"value": "transCodeName","label": "交易码名称"},{"value": "retCode","label": "交易返回码"}]', 'value值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725271640874, NULL, 20200321, 1725271664531, 'json');
INSERT INTO tb_base_menu (menu_id,menu_name,parent_id,service_name,`path`,menu_key,menu_type,menu_category,menu_sort,route,`method`,remark,icon,is_request,is_home,status,created,created_by,updated,updated_by) VALUES
    (1109282693036643,'首页',1118149469626864,'aimeter','overview','overview','page','leftMenu',1,NULL,'',NULL,'icon-description-line',0,1,0,1725355853046,20200321,1725413586340,20200321);
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES (1731498244587521, 'log_scene_analysis', 'log_scene_analysis_metric', '[{"label": "请求数","key": "count"},{"label": "系统错误率","key": "errorRate"},{"label": "系统错误数","key": "errorCount"},{"label": "平均响应时间","key": "avgDuration"},{"label": "关联告警数","key": "alertCount"}]', 'key值仅用于唯一标识该条配置，禁止修改', NULL, 20200321, 1725257132952, NULL, 5405847568024576, 1725434272023, 'json');
UPDATE tb_dict SET value='{
  "enable": true,
  "queryRange": 7,
  "combinedStandardDefaultValue": 10,
  "meanPercentage": 1.3,
  "rules": [
    {
      "start": 0,
      "end": 2,
      "color": "#2D7CFA"
    },
    {
      "start": 2,
      "end": 3,
      "color": "#e6a23c"
    },
    {
      "start": 3,
      "end": null,
      "color": "#f56c6c"
    }
  ]
}' WHERE id = 1722965978531841;
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750926726674433,'transaction-link','analysis_link_mode','graph','交易链追踪-交易链路的默认展示模式
可选值：graph 或 table（其余无效值会被初始化为graph）',NULL,20200321,1725850043172,NULL,20200321,1725868228631,'text');
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750910204917761,'transaction-link','spl_field_query_logic','OR','跳转日志详情时spl语句的字段查询逻辑
可选值：OR 或 AND （其余无效值会被初始化为 OR）',NULL,20200321,1725849538968,NULL,20200321,1725868220460,'text');
INSERT INTO tb_dict (id,data_group,name,value,remark,creator,created_by,created,updater,updated_by,updated,`type`) VALUES
    (1750832863459329,'transaction-link','x6_graph_config','{
  "virtual": false
}','交易链路x6图表的全局配置',NULL,20200321,1725847178695,NULL,20200321,1725946131669,'json');
UPDATE tb_dict SET `value` = REPLACE(`value`, '\n', '') WHERE `data_group`='business_scene' AND `name`='business_scene_threshold_config';

INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2119668958166017, 'transaction-link', 'trans_analysis_page_time_filter', '["now-10m","now"]', '', NULL, 20200321, 1737103163029, NULL, 20200321, 1737103565766, 'json');

INSERT INTO tb_dict
(id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES(1842235715378178, 'log-search', 'stream_search_config', '{
  "singleQueryMaxCount": 100,
  "chunkDurationMinutes": 5
}', '', NULL, 20200321, 1728636572368, NULL, 20200321, 1728715955616, 'json');

INSERT INTO tb_dict
(id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES(1842235715378178, 'log-search', 'stream_search_config', '{
  "singleQueryMaxCount": 100,
  "chunkDurationMinutes": 5
}', '', NULL, 20200321, 1728636572368, NULL, 20200321, 1728715955616, 'json');

INSERT INTO tb_dict
(id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES(1900991391882242, 'log-search', 'spl_query_options', '{
  "dorisRexUseOriginFunction": "true"
}', '', NULL, 20200321, 1730429653316, NULL, 20200321, 1730429653316, 'json');

INSERT INTO tb_dict
(id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`)
VALUES(1900991391882242, 'log-search', 'spl_query_options', '{
  "dorisRexUseOriginFunction": "true"
}', '', NULL, 20200321, 1730429653316, NULL, 20200321, 1730429653316, 'json');

INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2278329464844290, 'system_source', 'self_health', '自健康', '', NULL, 20200321, 1741945097437, NULL, 20200321, 1741947535430, 'text');
INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2278325688496129, 'system_source', 'license_manager', '许可证管控', '', NULL, 20200321, 1741944982192, NULL, 20200321, 1741947507750, 'text');

INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES(2317186577258498, 'log-search', 'search_query_mode', '[{"value":"sync","label":"即时搜索","tip":"发起搜索后，系统会检索所有符合条件的日志数据，完成后搜索结果一次性呈现，适用于数据规模适中场景"},{"value":"stream","label":"逐步搜索","tip":"发起搜索后，系统将检索范围按时间窗口划分，逐批次返回每个窗口符合条件的结果，适用于大规模数据探索和长时间运行的搜索场景"}]', '', NULL, 20200321, 1743130922402, NULL, 20200321, 1743401545567, 'json');

INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2249645329907713, 'apm', 'topo_node_levels', '{"request_count":[],"error_rate":[0.5,3,10],"duration_avg":[2000,4000,8000]}', 'apm服务拓扑服务节点填充默认配置（错误率、平均响应时间）', NULL, 20200321, 1741069727109, NULL, 20200321, 1741070564633, 'json');
INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES (2249650073174018, 'apm', 'service_matrix_trend_conf', '{"errorRateMaxY":0.1,"errorRateMax":0.01,"respTimeMaxY":5000,"respTimeMax":1000}', 'apm服务列表指标缩略图展示配置（错误率、平均响应时间）', NULL, 20200321, 1741069871862, NULL, 20200321, 1741070557578, 'json');
INSERT INTO `tb_dict` (`id`, `data_group`, `name`, `value`, `remark`, `creator`, `created_by`, `created`, `updater`, `updated_by`, `updated`, `type`) VALUES(2292464797387777, 'apm', 'topo_filter_types', '["Mysql","Kafka","Redis","Server"]', '链路追踪发现调用的未知 IP / 服务，这些对象疑似未接入链路 Agent', NULL, 20200321, 1742376473553, NULL, 20200321, 1742379520861, 'json');
INSERT INTO tb_dict (id, data_group, name, value, remark, creator, created_by, created, updater, updated_by, updated, `type`) VALUES(2326242669715457, 'apm', 'anomaly_analysis_settings', '{"season":1440,"step":5,"threshold":3,"returnAnomalyOnly":true,"score":{"total":{"requestCount":0.3,"respTime":0.35,"errorRate":0.35},"requestCount":[{"from":10,"score":0},{"from":5,"to":10,"score":0.2},{"from":3,"to":5,"score":0.5},{"from":0,"to":3,"score":0.8},{"to":0,"score":1}],"respTime":[{"from":10,"score":0},{"from":5,"to":10,"score":0.2},{"from":3,"to":5,"score":0.5},{"from":0,"to":3,"score":0.8},{"to":0,"score":1}],"errorRate":[{"from":10,"score":0},{"from":5,"to":10,"score":0.2},{"from":3,"to":5,"score":0.5},{"from":0,"to":3,"score":0.8},{"to":0,"score":1}]}}', '告警拓扑 异动/系统 分析预设配置', NULL, 20200321, 1743407292410, NULL, 20200321, 1743407349175, 'json');

