from main import engine

def application(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    status = engine.status()
    output = f"Themis is watching.\nLast scan: {status.get('last_scan','Never')}\n"
    return [output.encode()]
