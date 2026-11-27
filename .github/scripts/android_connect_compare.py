import argparse
import json
import re
import statistics
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from mock_clash_server import start_mock_servers


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


def dump_ui_nodes(out_path: Path):
    adb_shell('uiautomator', 'dump', '/sdcard/ui_dump.xml', timeout=30)
    xml_text = adb_shell('cat', '/sdcard/ui_dump.xml', timeout=20).stdout
    out_path.write_text(xml_text, encoding='utf-8')
    nodes = []
    if not xml_text.strip().startswith('<'):
        return nodes
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return nodes
    for elem in root.iter('node'):
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', elem.attrib.get('bounds', ''))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({
            'text': elem.attrib.get('text', ''),
            'desc': elem.attrib.get('content-desc', ''),
            'res_id': elem.attrib.get('resource-id', ''),
            'class': elem.attrib.get('class', ''),
            'clickable': elem.attrib.get('clickable') == 'true',
            'enabled': elem.attrib.get('enabled') == 'true',
            'bounds': (x1, y1, x2, y2),
            'cx': (x1 + x2) // 2,
            'cy': (y1 + y2) // 2,
        })
    return nodes


def tap(x: int, y: int, wait_s: float = 1.5):
    adb_shell('input', 'tap', str(x), str(y))
    time.sleep(wait_s)


def find_node(nodes, predicate):
    return next((n for n in nodes if predicate(n)), None)


def dismiss_system_anr(nodes):
    if not any("isn't responding" in f"{n['text']} {n['desc']}".lower() for n in nodes):
        return False
    btn = find_node(
        nodes,
        lambda n: 'close app' in f"{n['text']} {n['desc']}".lower() or 'wait' in f"{n['text']} {n['desc']}".lower(),
    )
    if btn:
        tap(btn['cx'], btn['cy'], 2.0)
        return True
    adb_shell('input', 'keyevent', 'KEYCODE_BACK')
    time.sleep(1.5)
    return True


def complete_disclaimer(app_dir: Path):
    nodes = dump_ui_nodes(app_dir / '00_launch.xml')
    if dismiss_system_anr(nodes):
        nodes = dump_ui_nodes(app_dir / '00_launch.xml')
    agree = find_node(
        nodes,
        lambda n: 'agree' in f"{n['text']} {n['desc']}".lower() and (n['clickable'] or 'Button' in n['class']),
    )
    if not agree:
        return False
    tap(agree['cx'], agree['cy'], 2.5)
    nodes = dump_ui_nodes(app_dir / '00_restate.xml')
    edit_node = find_node(nodes, lambda n: 'EditText' in n['class'])
    stmt_node = find_node(nodes, lambda n: len(n['text']) >= 40)
    if not edit_node or not stmt_node:
        return True
    statement = stmt_node['text'].strip()
    tap(edit_node['cx'], edit_node['cy'], 1.0)
    for start in range(0, len(statement), 20):
        chunk = statement[start:start + 20].replace(' ', '%s')
        adb_shell(f"input text '{chunk}'", timeout=30)
        time.sleep(0.2)
    time.sleep(1.0)
    typed_nodes = dump_ui_nodes(app_dir / '00_restate_typed.xml')
    confirm = find_node(
        typed_nodes,
        lambda n: 'confirm' in f"{n['text']} {n['desc']}".lower() and (n['clickable'] or 'Button' in n['class']),
    )
    if confirm:
        tap(confirm['cx'], confirm['cy'], 4.0)
        return True
    return False


def parse_meminfo(output: str):
    data = {}
    section = output.split('App Summary', 1)[1] if 'App Summary' in output else output
    for key, pat in {
        'total_pss_kb': r'TOTAL PSS:\s*(\d+)',
        'total_rss_kb': r'TOTAL RSS:\s*(\d+)',
        'native_heap_pss_kb': r'Native Heap:\s*(\d+)',
        'code_pss_kb': r'Code:\s*(\d+)',
    }.items():
        m = re.search(pat, section)
        if m:
            data[key.replace('_kb', '_mb')] = round(int(m.group(1)) / 1024.0, 2)
    return data


def sample_cpu(pid: str):
    if not pid:
        return None
    res = adb_shell('top', '-b', '-n', '3', '-d', '1', '-p', pid, timeout=20)
    samples = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == pid and len(parts) >= 9:
            try:
                samples.append(float(parts[8].rstrip('%')))
            except ValueError:
                pass
    return round(statistics.mean(samples), 2) if samples else None


def check_tun_up() -> bool:
    out = adb_shell('ip', 'addr', 'show').stdout
    return 'tun0' in out


def check_port_listening(port: int) -> bool:
    hex_port = f'{port:04X}'
    out = adb_shell('cat', '/proc/net/tcp', '/proc/net/tcp6').stdout
    return f':{hex_port} ' in out


def test_proxied_http(local_port: int, count: int = 3):
    adb('forward', '--remove-all')
    adb('forward', f'tcp:{local_port}', 'tcp:7890', check=True)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': f'http://127.0.0.1:{local_port}'}),
    )
    latencies = []
    errors = []
    for _ in range(count):
        t0 = time.perf_counter()
        try:
            with opener.open('http://10.0.2.2:18080/ping', timeout=8) as resp:
                body = resp.read().decode('utf-8')
                if resp.status == 200 and '"ok": true' in body:
                    latencies.append(round((time.perf_counter() - t0) * 1000, 1))
                else:
                    errors.append(f'HTTP {resp.status}: {body[:80]}')
        except Exception as exc:
            errors.append(str(exc)[:120])
        time.sleep(0.3)
    adb('forward', '--remove-all')
    return {
        'success_count': len(latencies),
        'total_count': count,
        'latencies_ms': latencies,
        'avg_latency_ms': round(statistics.mean(latencies), 1) if latencies else None,
        'errors': errors,
    }


def run_connection_test(name: str, apk_path: Path, package: str, out_dir: Path):
    app_dir = out_dir / name
    app_dir.mkdir(parents=True, exist_ok=True)
    state, sub_srv, proxy_srv = start_mock_servers(18080, 18081)
    try:
        adb('uninstall', package)
        adb('install', '-r', '-g', str(apk_path), timeout=120, check=True)
        adb_shell('pm', 'grant', package, 'android.permission.POST_NOTIFICATIONS')

        component = resolve_component(package)
        adb('logcat', '-c')
        adb_shell('am', 'start', '-W', '-n', component)
        time.sleep(5)

        disclaimer_ok = complete_disclaimer(app_dir)

        sub_url = 'clash://install-config?url=http%3A%2F%2F10.0.2.2%3A18080%2Fsub.yaml'
        t_import = time.perf_counter()
        adb_shell('am', 'start', '-a', 'android.intent.action.VIEW', '-d', sub_url, package)
        time.sleep(2.5)
        import_nodes = dump_ui_nodes(app_dir / '01_import_dialog.xml')
        confirm_import = find_node(
            import_nodes,
            lambda n: any(k in f"{n['text']} {n['desc']}".lower() for k in ('confirm', 'import', 'add', 'save', 'ok', '确定', '导入'))
            and ('Button' in n['class'] or n['clickable']),
        )
        if confirm_import and 'add profile' not in f"{confirm_import['text']} {confirm_import['desc']}".lower():
            tap(confirm_import['cx'], confirm_import['cy'], 2.0)

        import_elapsed_ms = None
        for _ in range(16):
            if state.snapshot()['sub_fetch_count'] > 0:
                import_elapsed_ms = round((time.perf_counter() - t_import) * 1000, 1)
                break
            time.sleep(0.5)
        time.sleep(3.0)
        screencap(app_dir / '01_after_import.png')

        nodes = dump_ui_nodes(app_dir / '02_nav_check.xml')
        start_btn = find_node(nodes, lambda n: f"{n['text']} {n['desc']}".strip().lower() == 'start')
        if not start_btn:
            drawer = find_node(nodes, lambda n: 'open navigation menu' in f"{n['text']} {n['desc']}".lower())
            if drawer:
                tap(drawer['cx'], drawer['cy'], 1.5)
                screencap(app_dir / '02_drawer.png')
                drawer_nodes = dump_ui_nodes(app_dir / '02_drawer.xml')
                dash = find_node(drawer_nodes, lambda n: 'dashboard' in f"{n['text']} {n['desc']}".lower())
                if dash:
                    tap(dash['cx'], dash['cy'], 2.5)
            else:
                dash = find_node(nodes, lambda n: 'dashboard' in f"{n['text']} {n['desc']}".lower() and n['clickable'])
                if dash:
                    tap(dash['cx'], dash['cy'], 2.5)

        screencap(app_dir / '03_dashboard_before_start.png')
        dash_nodes = dump_ui_nodes(app_dir / '03_dashboard_before_start.xml')
        start_btn = find_node(
            dash_nodes,
            lambda n: f"{n['text']} {n['desc']}".strip().lower() in ('start', 'connect', 'run', '启动'),
        )
        start_pos = None
        vpn_dialog_accepted = False
        if start_btn:
            start_pos = [start_btn['cx'], start_btn['cy']]
            tap(start_btn['cx'], start_btn['cy'], 2.5)
            vpn_nodes = dump_ui_nodes(app_dir / '04_vpn_dialog.xml')
            ok_btn = find_node(
                vpn_nodes,
                lambda n: n['res_id'] == 'android:id/button1' or f"{n['text']} {n['desc']}".strip().lower() == 'ok',
            )
            if ok_btn:
                tap(ok_btn['cx'], ok_btn['cy'], 1.0)
                vpn_dialog_accepted = True

        time.sleep(5.0)
        screencap(app_dir / '04_dashboard_connected.png')
        dump_ui_nodes(app_dir / '04_dashboard_connected.xml')

        services_connected = adb_shell('dumpsys', 'activity', 'services', package).stdout
        (app_dir / 'services_connected.txt').write_text(services_connected, encoding='utf-8')
        tun_up = check_tun_up()
        port_7890_open = check_port_listening(7890)
        http_test = test_proxied_http(17890, count=3) if port_7890_open else {
            'success_count': 0, 'total_count': 3, 'latencies_ms': [], 'avg_latency_ms': None, 'errors': ['port 7890 not listening'],
        }

        pid_conn = get_pid(package)
        mem_conn_raw = adb_shell('dumpsys', 'meminfo', package).stdout
        (app_dir / 'meminfo_connected.txt').write_text(mem_conn_raw, encoding='utf-8')
        mem_conn = parse_meminfo(mem_conn_raw)
        cpu_conn = sample_cpu(pid_conn)

        stop_clicked = False
        conn_nodes = dump_ui_nodes(app_dir / '05_before_stop.xml')
        stop_btn = find_node(
            conn_nodes,
            lambda n: f"{n['text']} {n['desc']}".strip().lower() in ('stop', 'disconnect', '停止'),
        )
        if stop_btn:
            tap(stop_btn['cx'], stop_btn['cy'], 3.5)
            stop_clicked = True
        elif start_pos:
            tap(start_pos[0], start_pos[1], 3.5)
            stop_clicked = True

        screencap(app_dir / '05_dashboard_stopped.png')
        tun_after_stop = check_tun_up()
        services_stopped = adb_shell('dumpsys', 'activity', 'services', package).stdout

        logcat_raw = adb('logcat', '-d', '-v', 'time').stdout
        filtered = [
            ln for ln in logcat_raw.splitlines()
            if any(tok in ln for tok in (package, 'flutter', 'Flutter', 'AndroidRuntime', 'FATAL', 'mihomo', 'GoLog', 'VpnService'))
        ]
        (app_dir / 'logcat_filtered.txt').write_text('\n'.join(filtered[-1500:]), encoding='utf-8')
        fatal_lines = [ln for ln in filtered if 'FATAL EXCEPTION' in ln or 'ANR in' in ln]

        mock_stats = state.snapshot()
        adb_shell('am', 'force-stop', package)
        adb('uninstall', package)

        return {
            'name': name,
            'package': package,
            'disclaimer_ok': disclaimer_ok,
            'sub_import': {
                'fetched': mock_stats['sub_fetch_count'] > 0,
                'fetch_count': mock_stats['sub_fetch_count'],
                'elapsed_ms': import_elapsed_ms,
                'user_agents': mock_stats['sub_user_agents'],
            },
            'vpn_start': {
                'start_btn_found': start_btn is not None,
                'vpn_dialog_accepted': vpn_dialog_accepted,
                'service_active': 'ServiceRecord' in services_connected,
                'tun0_up': tun_up,
                'mixed_port_7890_open': port_7890_open,
            },
            'proxy_forwarding': {
                'http_test': http_test,
                'upstream_proxy_hits': mock_stats['proxy_hits'],
                'target_ping_hits': mock_stats['ping_hits'],
                'proxy_targets': mock_stats['proxy_targets'],
            },
            'connected_resources': {
                'mem': mem_conn,
                'cpu_avg_percent': cpu_conn,
            },
            'vpn_stop': {
                'stop_clicked': stop_clicked,
                'tun0_still_up': tun_after_stop,
                'service_still_active': 'ServiceRecord' in services_stopped,
            },
            'fatal_or_anr': len(fatal_lines),
        }
    finally:
        sub_srv.shutdown()
        proxy_srv.shutdown()


def write_summary(results, out_path: Path):
    a, b = results[0], results[1]
    rows = [
        ('免责声明通过', a['disclaimer_ok'], b['disclaimer_ok']),
        ('本地订阅导入成功', a['sub_import']['fetched'], b['sub_import']['fetched']),
        ('订阅拉取耗时 (ms)', a['sub_import']['elapsed_ms'], b['sub_import']['elapsed_ms']),
        ('订阅请求 User-Agent', ', '.join(a['sub_import']['user_agents']) or '-', ', '.join(b['sub_import']['user_agents']) or '-'),
        ('点击启动按钮', a['vpn_start']['start_btn_found'], b['vpn_start']['start_btn_found']),
        ('系统 VPN 授权弹窗确认', a['vpn_start']['vpn_dialog_accepted'], b['vpn_start']['vpn_dialog_accepted']),
        ('Android Service 运行中', a['vpn_start']['service_active'], b['vpn_start']['service_active']),
        ('TUN 接口 (tun0) 就绪', a['vpn_start']['tun0_up'], b['vpn_start']['tun0_up']),
        ('本地混合端口 7890 监听', a['vpn_start']['mixed_port_7890_open'], b['vpn_start']['mixed_port_7890_open']),
        ('代理 HTTP 转发成功率', f"{a['proxy_forwarding']['http_test']['success_count']}/{a['proxy_forwarding']['http_test']['total_count']}", f"{b['proxy_forwarding']['http_test']['success_count']}/{b['proxy_forwarding']['http_test']['total_count']}"),
        ('代理转发平均延迟 (ms)', a['proxy_forwarding']['http_test']['avg_latency_ms'], b['proxy_forwarding']['http_test']['avg_latency_ms']),
        ('上游 Mock 代理命中次数', a['proxy_forwarding']['upstream_proxy_hits'], b['proxy_forwarding']['upstream_proxy_hits']),
        ('连接态内存 TOTAL PSS (MB)', a['connected_resources']['mem'].get('total_pss_mb'), b['connected_resources']['mem'].get('total_pss_mb')),
        ('连接态内存 TOTAL RSS (MB)', a['connected_resources']['mem'].get('total_rss_mb'), b['connected_resources']['mem'].get('total_rss_mb')),
        ('连接态 CPU 均值 (%)', a['connected_resources']['cpu_avg_percent'], b['connected_resources']['cpu_avg_percent']),
        ('停止后 tun0 已清理', not a['vpn_stop']['tun0_still_up'], not b['vpn_stop']['tun0_still_up']),
        ('FATAL / ANR 次数', a['fatal_or_anr'], b['fatal_or_anr']),
    ]
    lines = [
        f'# Connection Test Comparison: {a["name"]} vs {b["name"]}',
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
        results = [json.loads(Path(p).read_text(encoding='utf-8')) for p in args.merge]
        (out_dir / 'connect_comparison.json').write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        write_summary(results, out_dir / 'connect_summary.md')
        print((out_dir / 'connect_summary.md').read_text(encoding='utf-8'))
        return

    if not (args.app_name and args.apk and args.package):
        parser.error('Provide either --merge <a.json> <b.json> or --app-name/--apk/--package')

    res = run_connection_test(args.app_name, Path(args.apk), args.package, out_dir)
    (out_dir / f'{args.app_name}.json').write_text(
        json.dumps(res, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
