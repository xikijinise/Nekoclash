import http.server
import json
import select
import socket
import socketserver
import threading
import time
from urllib.parse import urlparse

SUB_YAML = """mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
proxies:
  - name: Mock-HTTP-Node
    type: http
    server: 10.0.2.2
    port: 18081
proxy-groups:
  - name: Proxy
    type: select
    proxies:
      - Mock-HTTP-Node
      - DIRECT
rules:
  - MATCH,Proxy
"""


class MockServerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.sub_requests = []
        self.ping_requests = 0
        self.proxy_requests = []

    def snapshot(self):
        with self.lock:
            return {
                'sub_fetch_count': len(self.sub_requests),
                'sub_user_agents': [r['ua'] for r in self.sub_requests],
                'ping_hits': self.ping_requests,
                'proxy_hits': len(self.proxy_requests),
                'proxy_targets': list(self.proxy_requests[:10]),
            }


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_sub_handler(state: MockServerState):
    class SubHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path.startswith('/sub.yaml'):
                ua = self.headers.get('User-Agent', '')
                with state.lock:
                    state.sub_requests.append({'ts': time.time(), 'ua': ua, 'path': self.path})
                body = SUB_YAML.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/yaml; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header(
                    'Subscription-Userinfo',
                    'upload=104857600; download=524288000; total=10737418240; expire=1893456000',
                )
                self.send_header('Profile-Title', 'MockTestSub')
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith('/ping'):
                with state.lock:
                    state.ping_requests += 1
                body = json.dumps({'ok': True, 'via': 'mock-target'}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

    return SubHandler


def _rewrite_host(host: str) -> str:
    return '127.0.0.1' if host == '10.0.2.2' else host


def _make_proxy_handler(state: MockServerState):
    class ProxyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_CONNECT(self):
            host, _, port_str = self.path.partition(':')
            port = int(port_str or 443)
            with state.lock:
                state.proxy_requests.append(f'CONNECT {self.path}')
            try:
                upstream = socket.create_connection((_rewrite_host(host), port), timeout=10)
            except OSError:
                self.send_error(502)
                return
            self.send_response(200, 'Connection Established')
            self.end_headers()
            self._tunnel(self.connection, upstream)
            upstream.close()

        def do_GET(self):
            parsed = urlparse(self.path)
            host = parsed.hostname or self.headers.get('Host', '').split(':')[0]
            port = parsed.port or 80
            path = parsed.path or '/'
            if parsed.query:
                path = f'{path}?{parsed.query}'
            with state.lock:
                state.proxy_requests.append(f'GET {host}:{port}{path}')
            try:
                upstream = socket.create_connection((_rewrite_host(host), port), timeout=10)
            except OSError:
                self.send_error(502)
                return
            req = f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n'
            upstream.sendall(req.encode('utf-8'))
            while True:
                data = upstream.recv(4096)
                if not data:
                    break
                self.wfile.write(data)
            upstream.close()

        def _tunnel(self, client_sock, upstream_sock):
            sockets = [client_sock, upstream_sock]
            while True:
                readable, _, _ = select.select(sockets, [], [], 10)
                if not readable:
                    break
                for sock in readable:
                    other = upstream_sock if sock is client_sock else client_sock
                    data = sock.recv(8192)
                    if not data:
                        return
                    other.sendall(data)

    return ProxyHandler


def start_mock_servers(sub_port=18080, proxy_port=18081):
    state = MockServerState()
    sub_srv = ThreadedHTTPServer(('0.0.0.0', sub_port), _make_sub_handler(state))
    proxy_srv = ThreadedHTTPServer(('0.0.0.0', proxy_port), _make_proxy_handler(state))
    threading.Thread(target=sub_srv.serve_forever, daemon=True).start()
    threading.Thread(target=proxy_srv.serve_forever, daemon=True).start()
    return state, sub_srv, proxy_srv
