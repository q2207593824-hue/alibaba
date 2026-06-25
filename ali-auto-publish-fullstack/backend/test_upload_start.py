import json, urllib.request as u, urllib.error as e
base='http://127.0.0.1:8000'

data=json.dumps({'mode':'batch','max_products':1}).encode()
req=u.Request(base+'/api/upload/start', data=data, method='POST', headers={'Content-Type':'application/json'})
try:
    r=u.urlopen(req, timeout=30)
    print('STATUS', r.status)
    print(r.read().decode('utf-8','ignore'))
except e.HTTPError as ex:
    print('HTTP', ex.code)
    print(ex.read().decode('utf-8','ignore'))
except Exception as ex:
    print('ERR', type(ex).__name__, ex)
