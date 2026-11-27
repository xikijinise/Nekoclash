import argparse
import json
import os
import re
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def run_cmd(cmd, timeout=60, check=False):
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f'Command failed ({proc.returncode}): {cmd}\n{proc.stderr}')
    return proc


def adb(*args, timeout=60, check=False):
    return run_cmd(['adb', *args], timeout=timeout, check=check)


def adb_shell(*args, timeout=60, check=False):
    return adb('shell', *args, timeout=timeout, check=check)


def inspect_apk(apk_path: Path):
    size_bytes = apk_path.stat().st_size
    so_files = {}
    total_so_bytes = 0
    with zipfile.ZipFile(apk_path, 'r') as zf:
        for info in zf.infolist():
            if info.filename.endswith('.so'):
                so_files[info.filename] = info.file_size
                total_so_bytes += info.file_size
    top_so = sorted(so_files.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        'file': apk_path.name,
        'size_bytes': size_bytes,
        'size_mb': round(size_bytes / (1024 * 1024), 2),
        'so_count': len(so_files),
        'total_so_mb': round(total_so_bytes / (1024 * 1024), 2),
        'top_so': [
            {'name': name, 'size_mb': round(sz / (1024 * 1024), 2)}
            for name, sz in top_so
        ],
    }


def resolve_component(package: str) -> str:
    res = adb_shell('cmd', 'package', 'resolve-activity', '--brief', package)
    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if '/' in ln and package in ln:
            return ln
    return f'{package}/.MainActivity'


def get_pid(package: str):
    res = adb_shell('pidof', '-s', package)
    pid = res.stdout.strip()
    return pid if pid.isdigit() else None


def screencap(out_path: Path):
    proc = subprocess.run(
        ['adb', 'exec-out', 'screencap', '-p'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if proc.returncode == 0 and proc.stdout:
        out_path.write_bytes(proc.stdout)


def dump_ui_xml(out_path: Path) -> str:
    adb_shell('uiautomator', 'dump', '/sdcard/ui_dump.xml', timeout=30)
    res = adb_shell('cat', '/sdcard/ui_dump.xml', timeout=20)
    xml_text = res.stdout
    out_path.write_text(xml_text, encoding='utf-8')
    return xml_text


def parse_bounds(bounds_str: str):
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str or '')
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1, y1, x2, y2)


def get_screen_size():
    res = adb_shell('wm', 'size')
    m = re.search(r'(\d+)x(\d+)', res.stdout)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1080, 2400


def parse_ui_nodes(xml_text: str):
    nodes = []
    if not xml_text.strip().startswith('<'):
        return nodes
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return nodes
    for elem in root.iter('node'):
        bounds = parse_bounds(elem.attrib.get('bounds', ''))
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        nodes.append({
            'text': elem.attrib.get('text', ''),
            'desc': elem.attrib.get('content-desc', ''),
            'class': elem.attrib.get('class', ''),
            'clickable': elem.attrib.get('clickable') == 'true',
            'bounds': bounds,
            'cx': (x1 + x2) // 2,
            'cy': (y1 + y2) // 2,
            'width': x2 - x1,
            'height': y2 - y1,
        })
    return nodes


def try_dismiss_first_launch_dialog(nodes):
    keywords = [
        'agree', 'accept', 'continue', 'confirm', 'allow', 'ok',
        '同意', '接受', '继续', '确定', '允许', '我知道了',
    ]
    for node in nodes:
        label = f"{node['text']} {node['desc']}".strip().lower()
        if not label:
            continue
        if any(k in label for k in keywords) and (node['clickable'] or 'button' in node['class'].lower()):
            adb_shell('input', 'tap', str(node['cx']), str(node['cy']))
            return {'clicked': True, 'label': f"{node['text']} {node['desc']}".strip(), 'pos': [node['cx'], node['cy']]}
    return {'clicked': False, 'label': None}


def try_complete_restate_dialog(nodes, app_dir: Path):
    edit_node = next((n for n in nodes if 'EditText' in n['class']), None)
    stmt_node = next((n for n in nodes if len(n['text']) >= 40), None)
    if not edit_node or not stmt_node:
        return {'completed': False}
    statement = stmt_node['text'].strip()
    adb_shell('input', 'tap', str(edit_node['cx']), str(edit_node['cy']))
    time.sleep(1.0)
    chunk_size = 20
    for start in range(0, len(statement), chunk_size):
        chunk = statement[start:start + chunk_size].replace(' ', '%s')
        adb_shell(f"input text '{chunk}'", timeout=30)
        time.sleep(0.2)
    time.sleep(1.0)
    screencap(app_dir / '02b_restate_typed.png')
    typed_xml = dump_ui_xml(app_dir / '02b_restate_typed.xml')
    typed_nodes = parse_ui_nodes(typed_xml)
    confirm_node = next(
        (
            n for n in typed_nodes
            if 'confirm' in f"{n['text']} {n['desc']}".lower() or '确定' in f"{n['text']} {n['desc']}"
        ),
        None,
    )
    if confirm_node:
        adb_shell('input', 'tap', str(confirm_node['cx']), str(confirm_node['cy']))
        time.sleep(4.0)
        return {'completed': True, 'statement_len': len(statement), 'confirm_pos': [confirm_node['cx'], confirm_node['cy']]}
    return {'completed': False, 'statement_len': len(statement)}


def find_bottom_nav_targets(nodes, width: int, height: int):
    min_y = int(height * 0.82)
    candidates = []
    for n in nodes:
        x1, y1, x2, y2 = n['bounds']
        if y1 < min_y or n['width'] < 40 or n['height'] < 40:
            continue
        if n['width'] > int(width * 0.45):
            continue
        if n['clickable'] or n['desc'] or n['text']:
            candidates.append(n)
    dedup = []
    for n in sorted(candidates, key=lambda item: item['cx']):
        if not dedup or abs(n['cx'] - dedup[-1]['cx']) > int(width * 0.12):
            dedup.append(n)
        elif (n['desc'] or n['text']) and not (dedup[-1]['desc'] or dedup[-1]['text']):
            dedup[-1] = n
    return dedup[:5]


def parse_start_metrics(output: str):
    total = re.search(r'TotalTime:\s*(\d+)', output)
    wait = re.search(r'WaitTime:\s*(\d+)', output)
    return {
        'total_time_ms': int(total.group(1)) if total else None,
        'wait_time_ms': int(wait.group(1)) if wait else None,
    }


def parse_meminfo(output: str):
    data = {}
    summary_section = output.split('App Summary', 1)[1] if 'App Summary' in output else output
    patterns = {
        'total_pss_kb': r'TOTAL PSS:\s*(\d+)',
        'total_rss_kb': r'TOTAL RSS:\s*(\d+)',
        'java_heap_pss_kb': r'Java Heap:\s*(\d+)',
        'native_heap_pss_kb': r'Native Heap:\s*(\d+)',
        'code_pss_kb': r'Code:\s*(\d+)',
        'graphics_pss_kb': r'Graphics:\s*(\d+)',
        'private_other_pss_kb': r'Private Other:\s*(\d+)',
        'system_pss_kb': r'System:\s*(\d+)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, summary_section)
        if m:
            data[key] = int(m.group(1))
    if 'total_pss_kb' not in data:
        m = re.search(r'TOTAL\s+(\d+)\s+(\d+)', output)
        if m:
            data['total_pss_kb'] = int(m.group(1))
    for k in list(data.keys()):
        if k.endswith('_kb'):
            data[k.replace('_kb', '_mb')] = round(data[k] / 1024.0, 2)
    return data


def sample_cpu(pid: str):
    if not pid:
        return {'samples': [], 'avg_percent': None}
    res = adb_shell('top', '-b', '-n', '3', '-d', '1', '-p', pid, timeout=20)
    samples = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == pid and len(parts) >= 9:
            try:
                samples.append(float(parts[8].rstrip('%')))
            except ValueError:
                pass
    return {
        'samples': samples,
        'avg_percent': round(statistics.mean(samples), 2) if samples else None,
    }


def parse_gfxinfo(output: str):
    data = {}
    patterns = {
        'total_frames': r'Total frames rendered:\s*(\d+)',
        'janky_frames': r'Janky frames:\s*(\d+)\s*\(([\d.]+)%\)',
        'p50_ms': r'50th percentile:\s*(\d+)ms',
        'p90_ms': r'90th percentile:\s*(\d+)ms',
        'p95_ms': r'95th percentile:\s*(\d+)ms',
        'p99_ms': r'99th percentile:\s*(\d+)ms',
    }
    for key, pat in patterns.items():
        m = re.search(pat, output)
        if not m:
            continue
        if key == 'janky_frames':
            data['janky_frames'] = int(m.group(1))
            data['janky_percent'] = float(m.group(2))
        else:
            data[key] = int(m.group(1))
    return data


def benchmark_app(name: str, apk_path: Path, package: str, out_dir: Path):
    app_dir = out_dir / name
    app_dir.mkdir(parents=True, exist_ok=True)
    width, height = get_screen_size()

    adb('uninstall', package)
    apk_info = inspect_apk(apk_path)
    adb('install', '-r', '-g', str(apk_path), timeout=120, check=True)
    adb_shell('pm', 'grant', package, 'android.permission.POST_NOTIFICATIONS')

    component = resolve_component(package)
    adb('logcat', '-c')

    first_res = adb_shell('am', 'start', '-W', '-n', component)
    first_start = parse_start_metrics(first_res.stdout)
    time.sleep(5)
    screencap(app_dir / '01_first_launch.png')
    first_xml = dump_ui_xml(app_dir / '01_first_launch.xml')
    first_nodes = parse_ui_nodes(first_xml)

    consent_action = try_dismiss_first_launch_dialog(first_nodes)
    restate_action = {'completed': False}
    if consent_action['clicked']:
        time.sleep(2.5)
        screencap(app_dir / '02_after_consent.png')
        after_xml = dump_ui_xml(app_dir / '02_after_consent.xml')
        restate_action = try_complete_restate_dialog(parse_ui_nodes(after_xml), app_dir)
        screencap(app_dir / '02c_after_restate.png')

    cold_starts = []
    for i in range(3):
        adb_shell('am', 'force-stop', package)
        time.sleep(2)
        adb('logcat', '-c')
        res = adb_shell('am', 'start', '-W', '-n', component)
        metrics = parse_start_metrics(res.stdout)
        time.sleep(2)
        log_disp = adb('logcat', '-d', '-s', 'ActivityTaskManager:I').stdout
        disp_m = re.search(rf'Displayed\s+{re.escape(package)}[^\n]*\+(\d+)ms', log_disp)
        metrics['displayed_ms'] = int(disp_m.group(1)) if disp_m else None
        cold_starts.append(metrics)

    time.sleep(6)
    pid_idle = get_pid(package)
    screencap(app_dir / '03_dashboard.png')
    dash_xml = dump_ui_xml(app_dir / '03_dashboard.xml')
    dash_nodes = parse_ui_nodes(dash_xml)

    mem_idle_raw = adb_shell('dumpsys', 'meminfo', package).stdout
    (app_dir / 'meminfo_idle.txt').write_text(mem_idle_raw, encoding='utf-8')
    mem_idle = parse_meminfo(mem_idle_raw)
    cpu_idle = sample_cpu(pid_idle)
    services_raw = adb_shell('dumpsys', 'activity', 'services', package).stdout
    (app_dir / 'services.txt').write_text(services_raw, encoding='utf-8')

    adb_shell('dumpsys', 'gfxinfo', package, 'reset')
    nav_targets = find_bottom_nav_targets(dash_nodes, width, height)
    visited_tabs = []
    for idx, target in enumerate(nav_targets):
        adb_shell('input', 'tap', str(target['cx']), str(target['cy']))
        time.sleep(1.5)
        screencap(app_dir / f'04_tab_{idx}.png')
        adb_shell(
            'input', 'swipe',
            str(width // 2), str(int(height * 0.70)),
            str(width // 2), str(int(height * 0.30)), '250',
        )
        time.sleep(0.6)
        adb_shell(
            'input', 'swipe',
            str(width // 2), str(int(height * 0.30)),
            str(width // 2), str(int(height * 0.70)), '250',
        )
        time.sleep(0.6)
        visited_tabs.append({
            'index': idx,
            'label': f"{target['text']} {target['desc']}".strip(),
            'pos': [target['cx'], target['cy']],
        })

    if nav_targets:
        adb_shell('input', 'tap', str(nav_targets[0]['cx']), str(nav_targets[0]['cy']))
        time.sleep(1.0)

    gfx_raw = adb_shell('dumpsys', 'gfxinfo', package).stdout
    (app_dir / 'gfxinfo.txt').write_text(gfx_raw, encoding='utf-8')
    gfx = parse_gfxinfo(gfx_raw)

    mem_after_raw = adb_shell('dumpsys', 'meminfo', package).stdout
    (app_dir / 'meminfo_after_nav.txt').write_text(mem_after_raw, encoding='utf-8')
    mem_after = parse_meminfo(mem_after_raw)

    adb_shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(3)
    mem_bg_raw = adb_shell('dumpsys', 'meminfo', package).stdout
    mem_bg = parse_meminfo(mem_bg_raw)

    resume_res = adb_shell('am', 'start', '-W', '-n', component)
    warm_resume = parse_start_metrics(resume_res.stdout)
    time.sleep(2)
    pid_after = get_pid(package)
    screencap(app_dir / '05_resumed.png')

    logcat_raw = adb('logcat', '-d', '-v', 'time').stdout
    filtered_lines = [
        ln for ln in logcat_raw.splitlines()
        if any(tok in ln for tok in (package, 'flutter', 'Flutter', 'AndroidRuntime', 'FATAL', 'mihomo', 'clash', 'GoLog'))
    ]
    (app_dir / 'logcat_filtered.txt').write_text('\n'.join(filtered_lines[-1500:]), encoding='utf-8')
    error_lines = [ln for ln in filtered_lines if re.search(r'\sE[/\s]', ln)]
    fatal_lines = [ln for ln in filtered_lines if 'FATAL EXCEPTION' in ln or 'ANR in' in ln]

    adb_shell('am', 'force-stop', package)
    adb('uninstall', package)

    valid_totals = [c['total_time_ms'] for c in cold_starts if c['total_time_ms'] is not None]
    return {
        'name': name,
        'package': package,
        'component': component,
        'apk': apk_info,
        'first_launch': first_start,
        'first_launch_dialog': consent_action,
        'restate_dialog': restate_action,
        'cold_starts': cold_starts,
        'cold_start_median_ms': int(statistics.median(valid_totals)) if valid_totals else None,
        'cold_start_avg_ms': round(statistics.mean(valid_totals), 1) if valid_totals else None,
        'mem_idle': mem_idle,
        'cpu_idle': cpu_idle,
        'mem_after_nav': mem_after,
        'mem_background': mem_bg,
        'gfxinfo': gfx,
        'visited_tabs': visited_tabs,
        'warm_resume': warm_resume,
        'pid_survived_background': pid_idle is not None and pid_idle == pid_after,
        'logcat_stats': {
            'filtered_lines': len(filtered_lines),
            'error_lines': len(error_lines),
            'fatal_or_anr': len(fatal_lines),
        },
        'services_active': 'ServiceRecord' in services_raw,
    }


def write_summary_md(results, out_path: Path):
    a, b = results[0], results[1]
    rows = [
        ('APK 大小 (MB)', a['apk']['size_mb'], b['apk']['size_mb']),
        ('原生 .so 总大小 (MB)', a['apk']['total_so_mb'], b['apk']['total_so_mb']),
        ('首次启动 TotalTime (ms)', a['first_launch']['total_time_ms'], b['first_launch']['total_time_ms']),
        ('首次启动弹窗自动点击', a['first_launch_dialog']['clicked'], b['first_launch_dialog']['clicked']),
        ('冷启动中位数 TotalTime (ms)', a['cold_start_median_ms'], b['cold_start_median_ms']),
        ('冷启动均值 TotalTime (ms)', a['cold_start_avg_ms'], b['cold_start_avg_ms']),
        ('静置内存 TOTAL PSS (MB)', a['mem_idle'].get('total_pss_mb'), b['mem_idle'].get('total_pss_mb')),
        ('静置内存 TOTAL RSS (MB)', a['mem_idle'].get('total_rss_mb'), b['mem_idle'].get('total_rss_mb')),
        ('静置 Native Heap (MB)', a['mem_idle'].get('native_heap_pss_mb'), b['mem_idle'].get('native_heap_pss_mb')),
        ('静置 CPU 均值 (%)', a['cpu_idle']['avg_percent'], b['cpu_idle']['avg_percent']),
        ('操作后内存 TOTAL PSS (MB)', a['mem_after_nav'].get('total_pss_mb'), b['mem_after_nav'].get('total_pss_mb')),
        ('后台内存 TOTAL PSS (MB)', a['mem_background'].get('total_pss_mb'), b['mem_background'].get('total_pss_mb')),
        ('渲染总帧数', a['gfxinfo'].get('total_frames'), b['gfxinfo'].get('total_frames')),
        ('掉帧数 / 掉帧率 (%)', f"{a['gfxinfo'].get('janky_frames')} ({a['gfxinfo'].get('janky_percent')}%)", f"{b['gfxinfo'].get('janky_frames')} ({b['gfxinfo'].get('janky_percent')}%)"),
        ('帧耗时 P50 / P90 / P95 / P99 (ms)', f"{a['gfxinfo'].get('p50_ms')}/{a['gfxinfo'].get('p90_ms')}/{a['gfxinfo'].get('p95_ms')}/{a['gfxinfo'].get('p99_ms')}", f"{b['gfxinfo'].get('p50_ms')}/{b['gfxinfo'].get('p90_ms')}/{b['gfxinfo'].get('p95_ms')}/{b['gfxinfo'].get('p99_ms')}"),
        ('后台切回热启动 (ms)', a['warm_resume']['total_time_ms'], b['warm_resume']['total_time_ms']),
        ('后台切换进程存活', a['pid_survived_background'], b['pid_survived_background']),
        ('Logcat Error 行数', a['logcat_stats']['error_lines'], b['logcat_stats']['error_lines']),
        ('Logcat FATAL / ANR', a['logcat_stats']['fatal_or_anr'], b['logcat_stats']['fatal_or_anr']),
    ]
    lines = [
        f'# Android Emulator Comparison: {a["name"]} vs {b["name"]}',
        '',
        f'| 指标 | {a["name"]} | {b["name"]} |',
        '| --- | --- | --- |',
    ]
    for label, va, vb in rows:
        lines.append(f'| {label} | {va} | {vb} |')
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-name')
    parser.add_argument('--apk')
    parser.add_argument('--package')
    parser.add_argument('--merge', nargs=2)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.merge:
        results = [
            json.loads(Path(p).read_text(encoding='utf-8'))
            for p in args.merge
        ]
        (out_dir / 'comparison.json').write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        write_summary_md(results, out_dir / 'summary.md')
        print((out_dir / 'summary.md').read_text(encoding='utf-8'))
        return

    if not (args.app_name and args.apk and args.package):
        parser.error('Provide either --merge <a.json> <b.json> or --app-name/--apk/--package')

    result = benchmark_app(args.app_name, Path(args.apk), args.package, out_dir)
    (out_dir / f'{args.app_name}.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
