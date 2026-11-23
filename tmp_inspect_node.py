import json
import urllib.parse
import urllib.request
BASE='https://agentdock.link'
req=urllib.request.Request(BASE+'/api/v1/auth/token',data=json.dumps({'email':'mayintake351@gmail.com','password':'Stevohh@2024'}).encode(),headers={'Content-Type':'application/json'},method='POST')
tok=json.load(urllib.request.urlopen(req))['access_token']; h={'Authorization':'Bearer '+tok}
for slug,path in [('obra-superpowers-skills-brainstorming','scripts/helper.js'),('pbakaus-impeccable-agents-skills-impeccable','scripts/live-browser-ignores.js')]:
 url=BASE+f'/api/v1/skills/{slug}/resources/'+urllib.parse.quote(path)
 t=urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=30).read().decode('utf-8','replace')
 print('====',slug,path,'len',len(t)); print('\n'.join(t.splitlines()[:20]))
