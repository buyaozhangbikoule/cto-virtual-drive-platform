"""Read-only provenance overlay, never imported by controllers or load models.

Values here are declarations, NOT defaults. JSON/AST checks never execute a
research script or copy a literature value into a model.
"""
from __future__ import annotations
import ast
from copy import deepcopy
import json
import math
from pathlib import Path
from current.catalog import PLATFORM, inside, read_json

REGISTRY = PLATFORM / 'current/parameter_sources.json'
REQUIRED = ('id', 'name', 'unit', 'identity', 'group', 'frequency_scope',
            'measurement_conditions', 'adoption_reason', 'limitations', 'status')


def load_registry(path=REGISTRY):
    return read_json(path)


def numeric_setting(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return isinstance(value, list) and bool(value) and all(numeric_setting(v) for v in value)


def expand_registry(data):
    """Every exported entry includes the inherited provenance fields."""
    if data.get('schema_version') != 1:
        raise ValueError('不支持的参数登记版本')
    entries, seen = [], set()
    for raw in data['entries']:
        item = deepcopy(data['profiles'][raw['profile']])
        item.update(deepcopy(raw))
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in REQUIRED):
            raise ValueError(f'参数来源必填字段缺失：{raw.get("id")}')
        if item['id'] in seen:
            raise ValueError(f'参数ID重复：{item["id"]}')
        seen.add(item['id'])
        if not numeric_setting(item.get('value')):
            raise ValueError(f'登记值必须为有限数或数值列表：{item["id"]}')
        if not isinstance(item.get('formal_use'), bool):
            raise ValueError(f'缺少正式使用身份：{item["id"]}')
        if not item.get('source_ids') or any(s not in data['sources'] for s in item['source_ids']):
            raise ValueError(f'来源不存在：{item["id"]}')
        if 'config_key' in item:
            if 'binding' in item:
                raise ValueError('config_key与binding不能同时设置')
            item['binding'] = {'source': 'config', 'path': [item['config_key']]}
            if 'config' not in item['source_ids']:
                item['source_ids'].append('config')
        if 'binding' in item and item['binding']['source'] not in data['sources']:
            raise ValueError(f'数值绑定来源不存在：{item["id"]}')
        if item['profile'] in ('saijo', 'pending') and (item['formal_use'] or 'binding' in item):
            raise ValueError('文献参考／待核实范围不得绑定为运行参数')
        if item['profile'] == 'research' and item['formal_use']:
            raise ValueError('未接入原型不得标为正式使用')
        if item['profile'] == 'pending' and item['status'] != '待核实':
            raise ValueError('未溯源范围必须标记待核实')
        if item['profile'] == 'saijo' and (not numeric_setting(item.get('sd')) or item['sd'] < 0):
            raise ValueError('Saijo条目必须保留SD')
        if not numeric_setting(item.get('scale', 1)) or item.get('scale', 1) <= 0:
            raise ValueError('单位比例必须为有限正数')
        item['sources'] = [deepcopy(data['sources'][s]) for s in item['source_ids']]
        entries.append(item)
    return entries


def bound_value(binding, sources, root=PLATFORM):
    """Read declarations without eval, imports, or running the model."""
    path = inside(Path(root), sources[binding['source']]['path'])
    mode = binding.get('mode', 'json')
    if mode == 'json':
        value = read_json(path)
    elif mode in ('constant', 'keyword'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        matches = [n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == binding['name'] for t in n.targets)]
        if len(matches) != 1:
            raise ValueError(f'常量不是唯一声明：{binding["name"]}')
        node = matches[0]
        if mode == 'keyword':
            if not isinstance(node, ast.Call):
                raise ValueError('预期关键字赋值，实际声明已变化')
            nodes = [k.value for k in node.keywords if k.arg == binding['keyword']]
            if len(nodes) != 1:
                raise ValueError('关键字缺失或重复')
            node = nodes[0]
        value = ast.literal_eval(node)
    else:
        raise ValueError(f'不支持的只读绑定：{mode}')
    for key in binding.get('path', []):
        value = value[key]
    return value


def check_registry(data=None, root=PLATFORM):
    data = data or load_registry()
    entries = expand_registry(data)
    issues = []
    for item in entries:
        if 'binding' not in item:
            item['value_check'] = '无运行绑定（设计说明／文献参考／待核实）'
            continue
        try:
            actual = bound_value(item['binding'], data['sources'], root)
            item['source_value'] = actual
            if actual != item['value']:
                item['value_check'] = '不一致：需更新登记并复核；不自动采用新值'
                issues.append(f'{item["id"]}：登记值与当前文件不一致')
            else:
                item['value_check'] = '与所列文件一致（不代表物理有效性）'
        except (OSError, ValueError, KeyError, IndexError, TypeError, SyntaxError) as exc:
            item['value_check'] = f'未完成核对：{exc}'
            issues.append(f'{item["id"]}：来源缺失或无法读取')
    try:
        cfg = read_json(inside(Path(root), data['sources']['config']['path']))
        keys = {k for k, v in cfg.items() if numeric_setting(v)}
        covered = {e['config_key'] for e in entries if 'config_key' in e}
        for key in sorted(keys - covered):
            issues.append(f'配置数值参数尚未登记：{key}')
        for key in sorted(covered - keys):
            issues.append(f'登记绑定不是当前数值参数：{key}')
    except (OSError, ValueError, KeyError):
        issues.append('不能核对正式配置覆盖范围')
    return {'schema_version': 1, 'updated': data['updated'], 'scope': data['scope'],
            'ok': not issues, 'issues': issues, 'entries': entries}


def format_value(entry):
    scale = entry.get('scale', 1)
    unit = entry.get('display_unit', entry['unit'])

    def scalar(value):
        return f'{value * scale:.9g}'

    value = entry['value']
    if entry['id'] == 'scan_levels_Hz':
        return ' → '.join(f'±{scalar(w)} / {scalar(s)}' for w, s in value) + f' {unit}'
    if isinstance(value, list):
        return '–'.join(scalar(v) for v in value) + f' {unit}（待核实范围）'
    if 'sd' in entry:
        return f'{scalar(value)} ± {scalar(entry["sd"])} {unit}（均值±SD）'
    return f'{scalar(value)} {unit}'


def registry_json(result):
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    result = check_registry()
    print(registry_json({'ok': result['ok'], 'parameters': len(result['entries']), 'issues': result['issues']}))
    raise SystemExit(0 if result['ok'] else 1)
