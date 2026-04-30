import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from themis.engine import ThemisEngine

_engine = ThemisEngine()

def application(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    status = _engine.status()
    last_scan = status.get('last_scan', 'Never')
    output = f"Themis is watching.\nLast scan: {last_scan}\nVersion: 1.0.0\n"
    return [output.encode()]
