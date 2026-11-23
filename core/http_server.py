# -*- coding: utf-8 -*-
"""
HTTP 文件服务模块 — 使用 http.server 提供安装包下载
"""
import os
import posixpath
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn


class _PackageRequestHandler(SimpleHTTPRequestHandler):
    """从指定目录提供文件服务，避免 os.chdir 影响进程级 CWD"""

    def __init__(self, *args, **kwargs):
        # SimpleHTTPRequestHandler 根据 CWD 决定服务根目录，
        # 通过 translate_path 重写使其基于指定目录
        self.base_dir = kwargs.pop('base_dir', os.getcwd())
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        """重写路径解析，以 base_dir 为根目录"""
        path = posixpath.normpath(path)
        words = path.split('/')
        words = filter(None, words)
        result = self.base_dir
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir):
                continue
            result = os.path.join(result, word)
        return result


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，每个请求在独立线程中处理"""
    daemon_threads = True
    allow_reuse_address = True


class HTTPServerThread(threading.Thread):
    """在后台线程中启动 HTTP 文件服务，供远程主机下载安装包"""

    def __init__(self, package_dir, port=8000):
        super().__init__(daemon=True)
        self.package_dir = os.path.abspath(package_dir)
        self.port = port
        self.httpd = None

    def run(self):
        """启动 HTTP 服务，以 package_dir 为根目录"""
        server_address = ('0.0.0.0', self.port)

        def handler(*args):
            _PackageRequestHandler(*args, base_dir=self.package_dir)

        self.httpd = _ThreadedHTTPServer(server_address, handler)
        self.httpd.serve_forever()

    def stop(self):
        """停止 HTTP 服务"""
        if self.httpd:
            self.httpd.shutdown()
