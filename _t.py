import httpx, json
r = httpx.post('http://127.0.0.1:8000/api/projects', json={'name': 'test', 'style': '电影感'})
print(r.status_code, r.text[:300])
