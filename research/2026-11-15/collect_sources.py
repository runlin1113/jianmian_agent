"""Read-only upstream research; save pinned metadata and source excerpts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import urllib.request
import urllib.parse
import subprocess
import hashlib
import sys
import re

ROOT = Path(__file__).resolve().parent / 'upstream'
ROOT.mkdir(exist_ok=True)
REPOS = [
    'langchain-ai/langgraph', 'pydantic/pydantic-ai', 'openai/openai-agents-python',
    'agno-agi/agno', 'langgenius/dify', 'coze-dev/coze-studio',
    'AmruthPillai/Reactive-Resume', 'xitanggg/open-resume',
    'srbhr/Resume-Matcher', 'danielvolchek/ResuLLMe',
    'mozilla/pdf.js', 'docling-project/docling', 'microsoft/markitdown',
    'jlifeng/JobPilot', 'AlanYy-42/JD-Scout', 'Programmergyt/ai-career-copilot',
]

def get(url, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent':'Jianmian-Architecture-Research', 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = response.read()
    return data if binary else data.decode('utf-8')

def collect_raw(repo):
    folder=ROOT.parent/'verified'/repo.replace('/','__')
    folder.mkdir(parents=True,exist_ok=True)
    record={'repo':repo,'retrieved_at':datetime.now(timezone.utc).isoformat(),'files':{},'errors':[]}
    old=ROOT/repo.replace('/','__')/'metadata.json'
    prev=json.loads(old.read_text(encoding='utf-8')) if old.exists() else {}
    ref=prev.get('commit','HEAD')
    try:
        page=get('https://github.com/'+repo)
        match=re.search(r'"currentOid":"([a-f0-9]{40})"',page)
        if match: ref=match.group(1)
    except Exception as exc: record['errors'].append('repository page: '+str(exc))
    record['ref']=ref
    for candidates in [['README.md','readme.md'],['LICENSE','LICENSE.md','LICENSE.txt']]:
        for path in candidates:
            try:
                url='https://raw.githubusercontent.com/'+repo+'/'+ref+'/'+path
                data=get(url,binary=True)
                (folder/path).write_bytes(data)
                record['files'][path]={'sha256':hashlib.sha256(data).hexdigest(),'url':url}
                break
            except urllib.error.HTTPError as exc:
                if exc.code!=404: record['errors'].append(path+': '+str(exc)); break
            except Exception as exc: record['errors'].append(path+': '+str(exc)); break
    (folder/'metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record

def collect_git(repo):
    folder=ROOT.parent/'git_sources'/repo.replace('/','__')
    checkout=folder/'repository'
    folder.mkdir(parents=True,exist_ok=True)
    record={'repo':repo,'retrieved_at':datetime.now(timezone.utc).isoformat(),'files':{},'errors':[]}
    git=r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
    def command(args):
        result=subprocess.run([git]+args,capture_output=True,timeout=90,check=True)
        return result.stdout
    try:
        if not checkout.exists():
            command(['clone','--depth','1','--filter=blob:none','--no-checkout','https://github.com/'+repo+'.git',str(checkout)])
        record['commit']=command(['-C',str(checkout),'rev-parse','HEAD']).decode().strip()
        record['commit_date']=command(['-C',str(checkout),'show','-s','--format=%cI','HEAD']).decode().strip()
        paths=command(['-C',str(checkout),'ls-tree','-r','--name-only','HEAD']).decode('utf-8').splitlines()
        (folder/'tree.txt').write_text('\n'.join(paths),encoding='utf-8')
        selected=[p for p in paths if '/' not in p and (p.lower() in ['readme.md','license','license.md','license.txt','notice','notice.md','package.json','pyproject.toml'])]
        for path in selected:
            data=command(['-C',str(checkout),'show','HEAD:'+path])
            (folder/path).write_bytes(data)
            record['files'][path]={'sha256':hashlib.sha256(data).hexdigest(),'url':'https://github.com/'+repo+'/blob/'+record['commit']+'/'+path}
    except Exception as exc: record['errors'].append(str(exc)+(' '+exc.stderr.decode('utf-8',errors='replace')[-1800:] if isinstance(exc,subprocess.CalledProcessError) else ''))
    (folder/'metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record

if '--git-only' in sys.argv:
    records=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(collect_git,repo) for repo in REPOS]):
            record=future.result()
            records.append(record)
            print(json.dumps({'repo':record['repo'],'commit':record.get('commit'),'files':list(record['files']),'errors':record['errors']},ensure_ascii=True),flush=True)
    (ROOT.parent/'git_sources'/'index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0)

if '--probe' in sys.argv:
    repo='langchain-ai/langgraph'
    print(json.dumps(collect_git(repo),ensure_ascii=True),flush=True)
    sys.exit(0)

if '--raw' in sys.argv:
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(collect_raw,repo) for repo in REPOS]):
            record=future.result()
            records.append(record)
            print(json.dumps({'repo':record['repo'],'ref':record['ref'],'files':list(record['files']),'errors':record['errors']},ensure_ascii=True),flush=True)
    (ROOT.parent/'verified'/'index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0)

def collect(repo):
    folder = ROOT / repo.replace('/', '__')
    folder.mkdir(exist_ok=True)
    record = {'repo': repo, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    try:
        previous = folder/'metadata.json'
        if previous.exists():
            record.update(json.loads(previous.read_text(encoding='utf-8')))
            record.pop('error',None)
        git = r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
        refs=subprocess.run([git,'ls-remote','--symref','https://github.com/'+repo+'.git','HEAD'],capture_output=True,text=True,timeout=50,check=True).stdout
        for line in refs.splitlines():
            if line.startswith('ref: refs/heads/'):
                record['default_branch']=line.split()[1].removeprefix('refs/heads/')
            elif line.endswith('\tHEAD'):
                record['commit']=line.split()[0]
        record['retrieved_at']=datetime.now(timezone.utc).isoformat()
        record['html_url']='https://github.com/'+repo
        record['files']={}
        for candidates in [['README.md','readme.md','README.en.md'],['LICENSE','LICENSE.md','LICENSE.txt','license'],['NOTICE','NOTICE.md']]:
            for path in candidates:
                try:
                    data=get('https://raw.githubusercontent.com/'+repo+'/'+record['commit']+'/'+path,binary=True)
                    (folder/path).write_bytes(data)
                    record['files'][path]={'sha256':hashlib.sha256(data).hexdigest(),'url':'https://github.com/'+repo+'/blob/'+record['commit']+'/'+path}
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code!=404: raise
    except Exception as exc:
        record['error']=str(exc)
    (folder/'metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record

records=[]
with ThreadPoolExecutor(max_workers=5) as pool:
    for future in as_completed([pool.submit(collect, repo) for repo in REPOS]):
        record=future.result()
        records.append(record)
        print(json.dumps({'repo':record['repo'],'commit':record.get('commit'),'files':list(record.get('files',{})),'error':record.get('error')},ensure_ascii=True),flush=True)
(ROOT/'index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

for query in []:
    try:
        data=json.loads(get('https://api.github.com/search/repositories?'+urllib.parse.urlencode({'q':query,'sort':'stars','per_page':6})))
        name='search__'+query.replace(' ','_')+'.json'
        (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'query':query,'results':[{'repo':x['full_name'],'description':x['description'],'stars':x['stargazers_count']} for x in data['items']]},ensure_ascii=True),flush=True)
    except Exception as exc:
        print(json.dumps({'query':query,'error':str(exc)}),flush=True)
