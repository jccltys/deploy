#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spring 配置文件占位符替换工具

替换 .properties / .yml / .yaml 文件中的占位符:
    ${ENV_NAME:default_value}  ->  new_value  (with --inline)
    ${ENV_NAME:default_value}  ->  ${ENV_NAME:new_value}  (default)

用法:
  # 1. 先扫描文件，查看有哪些占位符
  python3 deploy/utils/update_spring_config.py --file application.properties --scan

  # 2. 复制扫描结果，修改值后执行替换
  python3 deploy/utils/update_spring_config.py \
      --file application.properties \
      --replace NACOS_HOST=192.168.1.100:8848 \
      --replace MYSQL_HOST=192.168.1.100:3306 \
      --inline
"""
import argparse
import logging
import os
import re
import sys


class SpringConfigUpdater:

    @staticmethod
    def replace_placeholder(content, env_name, new_value, inline=False):
        # inline=True: 将 ${VAR:default} 完全替换为实际值
        # inline=False: 只替换默认值部分 → ${VAR:new_value}（保留变量引用）
        if inline:
            pattern = r'\$\{' + re.escape(env_name) + r':[^}]*\}'
            return re.sub(pattern, str(new_value), content)
        pattern = r'(\$\{' + re.escape(env_name) + r':)([^}]*)(})'
        return re.sub(pattern, lambda m: m.group(1) + str(new_value) + m.group(3), content)

    @staticmethod
    def batch_replace(content, replace_map, inline=False):
        for env_name, new_value in replace_map.items():
            content = SpringConfigUpdater.replace_placeholder(
                content, env_name, new_value, inline
            )
        return content

    @staticmethod
    def scan_placeholders(file_path):
        if not os.path.isfile(file_path):
            logging.error('文件不存在: %s', file_path)
            sys.exit(1)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*):([^}]*)\}'
        matches = re.findall(pattern, content)

        placeholders = {}
        for env_name, default_value in matches:
            if env_name not in placeholders:
                placeholders[env_name] = default_value

        return placeholders

    @staticmethod
    def update_file(file_path, replace_map, inline=False):
        if not os.path.isfile(file_path):
            logging.error('文件不存在: %s', file_path)
            sys.exit(1)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        content = SpringConfigUpdater.batch_replace(content, replace_map, inline)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        logging.info('配置更新完成: %s', file_path)
        return content


def parse_replace_args(replace_args):
    replace_map = {}
    for arg in replace_args:
        if '=' not in arg:
            logging.error('--replace 参数格式错误: %s（应为 ENV_NAME=VALUE）', arg)
            sys.exit(1)
        key, value = arg.split('=', 1)
        replace_map[key] = value
    return replace_map


def main():
    parser = argparse.ArgumentParser(description='Spring 配置文件占位符替换工具')
    parser.add_argument(
        '--file', '-f',
        required=True,
        action='append',
        help='目标配置文件路径（可多次使用）'
    )
    parser.add_argument(
        '--replace', '-r',
        action='append',
        default=[],
        help='替换项，格式: ENV_NAME=VALUE（可多次使用）'
    )
    parser.add_argument(
        '--scan',
        action='store_true',
        help='扫描文件中的占位符并列出（不执行替换）'
    )
    parser.add_argument(
        '--inline',
        action='store_true',
        help='将 ${ENV:default} 完全替换为实际值（否则只替换默认值）'
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='仅预览替换结果，不写入文件'
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    if args.scan:
        for file_path in args.file:
            logging.info('=== [%s] 扫描结果 ===', file_path)
            placeholders = SpringConfigUpdater.scan_placeholders(file_path)
            if not placeholders:
                logging.info('未发现占位符')
                continue
            logging.info('发现 %d 个占位符:', len(placeholders))
            for env_name, default_value in placeholders.items():
                logging.info('  --replace %s=%s', env_name, default_value)
        return

    if not args.replace:
        logging.error('未提供替换项。使用 --replace 指定，或先用 --scan 查看文件中的占位符。')
        sys.exit(1)

    replace_map = parse_replace_args(args.replace)

    for file_path in args.file:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        updated_content = SpringConfigUpdater.batch_replace(
            original_content, replace_map, inline=args.inline
        )

        if args.dry_run:
            logging.info('--- [%s] 预览模式 ---', file_path)
            logging.info(updated_content)
            continue

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)

        logging.info('配置更新完成: %s', file_path)

    if not args.dry_run:
        logging.info('共处理 %d 个文件，替换 %d 个占位符', len(args.file), len(replace_map))


if __name__ == '__main__':
    main()
