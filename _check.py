import httpx, json
r = httpx.get('http://127.0.0.1:8000/api/projects/1/assets')
d = r.json()
for a in d:
    print(f'--- #{a["id"]} [{a["type"]}] {a["name"]} ---')
    print(a.get('description', '(无description)')[:200])
    print()
