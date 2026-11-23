#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描所有 Installer，收集模板变量文档，生成 Markdown 表格

用法:
    python3 deploy/tools/generate_var_docs.py
"""
import logging
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SCRIPT_DIR)

from install import import_installers


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    registry, _ = import_installers()

    lines = []
    lines.append('# 配置模板变量参考（自动生成）\n')

    for name, cls in sorted(registry.items()):
        if not hasattr(cls, 'get_template_vars_doc'):
            continue
        vars_doc = cls.get_template_vars_doc()
        if not vars_doc:
            continue

        lines.append('## {}\n'.format(name))
        lines.append('| 变量 | 类型 | 说明 | 来源 | 示例 |')
        lines.append('|------|------|------|------|------|')
        for var, meta in sorted(vars_doc.items()):
            lines.append('| `${{{}}}` | {} | {} | {} | {} |'.format(
                var,
                meta.get('type', '-'),
                meta.get('description', '-'),
                meta.get('source', '-'),
                meta.get('example', '-')
            ))
        lines.append('')

    # 写入 deploy/docs/template-vars.md
    docs_dir = os.path.join(_SCRIPT_DIR, 'docs')
    output_path = os.path.join(docs_dir, 'template-vars.md')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logging.info('已生成: %s（%d 个组件）', output_path, len(registry))


if __name__ == '__main__':
    main()
