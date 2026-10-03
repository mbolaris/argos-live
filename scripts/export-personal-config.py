#!/usr/bin/env python3
"""Export configuration as inert, secret-redacted reference data; never activate it."""
import hashlib,json,os,pathlib,re,sys,zipfile

PRIVATE={'apikey','token','accesstoken','refreshtoken','password','passphrase','clientsecret','privatekey','authorization','cookie','cookies','auth','authentication','credentials','secrets','headers','env','environment'}
PATTERNS=[re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),re.compile(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b'),re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----',re.S)]
def sensitive(key):
    norm=re.sub('[^a-z0-9]','',key.lower())
    return norm in PRIVATE or norm.endswith('apikey') or norm.endswith('accesstoken') or norm.endswith('refreshtoken')

def export(source,destination):
    source=pathlib.Path(source).resolve(); destination=pathlib.Path(destination).resolve()
    if not destination.is_dir() or any(destination.iterdir()):raise ValueError('Private destination must be an existing empty directory')
    config=json.loads((source/'openclaw.json').read_text(encoding='utf-8-sig'))
    known=set(); redactions=[]; skipped=[]
    def linked(p):
        return p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction())
    def regular_files(root,pattern):
        if linked(root):
            skipped.append(dict(source=str(root),reason='Linked directory; runtime reference only'))
            return
        for current,dirs,names in os.walk(root,followlinks=False):
            for name in list(dirs):
                p=pathlib.Path(current)/name
                if linked(p) or name.startswith('.'):
                    dirs.remove(name)
                    skipped.append(dict(source=str(p),reason='Linked or hidden directory excluded'))
            for name in names:
                p=pathlib.Path(current)/name
                if not p.match(pattern):continue
                if linked(p) or not p.resolve().is_relative_to(root.resolve()):
                    skipped.append(dict(source=str(p),reason='Linked file excluded'))
                    continue
                yield p
    def leaves(value):
        if isinstance(value,str) and len(value)>=8 and not any(x in value for x in ('${','<REDACTED>')):known.add(value)
        elif isinstance(value,dict):
            for v in value.values():leaves(v)
        elif isinstance(value,list):
            for v in value:leaves(v)
    def gather(value,group=False):
        if isinstance(value,dict):
            for k,v in value.items():
                if group or sensitive(k):leaves(v)
                else:gather(v)
        elif isinstance(value,list):
            for v in value:gather(v,group)
    gather(config)
    # Read secrets only in memory to prevent their literal values entering copied text.
    credential_files=[source/'secrets.json']
    if (source/'credentials').is_dir():credential_files+=list(regular_files(source/'credentials','*.json'))
    for p in credential_files:
        if p.is_file() and not linked(p) and p.resolve().is_relative_to(source) and p.stat().st_size<2_000_000:
            try:gather(json.loads(p.read_text(encoding='utf-8-sig')),True)
            except (ValueError,UnicodeError):pass
    def clean_text(text):
        count=0
        for value in sorted(known,key=len,reverse=True):
            if value in text:count+=text.count(value);text=text.replace(value,'<REDACTED>')
        for pattern in PATTERNS:
            text,n=pattern.subn('<REDACTED>',text);count+=n
        return text,count
    def sanitize(value,path=''):
        if isinstance(value,dict):
            result={}
            for k,v in value.items():
                if sensitive(k):result[k]='<REDACTED>';redactions.append(path+'.'+k)
                else:result[k]=sanitize(v,path+'.'+k)
            return result
        if isinstance(value,list):return [sanitize(v,path+f'[{i}]') for i,v in enumerate(value)]
        if isinstance(value,str):return clean_text(value)[0]
        return value
    files={};inventory=[]
    def add(name,data,origin):
        files[name]=data;inventory.append(dict(path=name,source=str(origin),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    add('reference/openclaw.redacted.json',(json.dumps(sanitize(config),indent=2,ensure_ascii=False)+'\n').encode(),source/'openclaw.json')
    entries=config.get('agents',{}).get('entries',{})
    if not isinstance(entries,dict):raise ValueError('Inspect unsupported source agent schema before exporting')
    profiles=[];core={'AGENTS.md','SOUL.md','IDENTITY.md','USER.md','MEMORY.md','DREAMS.md','HEARTBEAT.md','TOOLS.md','TOOLS.md.pre-move','README.md'}
    for agent_id,entry in entries.items():
        if entry.get('name') not in ('Argos','Nyx','Proteus'):continue
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',agent_id):raise ValueError('Unsafe profile identifier')
        workspace=pathlib.Path(entry['workspace']).resolve()
        profiles.append(dict(id=agent_id,name=entry['name'],sourceWorkspace=str(workspace),exportWorkspace='profiles/'+agent_id,settings=sanitize(entry)))
        candidates=[p for p in workspace.iterdir() if p.is_file() and p.name in core]
        skillroot=workspace/'skills'
        if skillroot.is_dir():candidates+=list(regular_files(skillroot,'*.md'))
        for p in candidates:
            if linked(p) or not p.resolve().is_relative_to(workspace):
                skipped.append(dict(source=str(p),reason='Linked file excluded'));continue
            if p.stat().st_size>2_000_000:continue
            rel=p.resolve().relative_to(workspace)
            if any(part.startswith('.') for part in rel.parts):continue
            text,n=clean_text(p.read_text(encoding='utf-8-sig'))
            if n:redactions.append('text:'+agent_id+'/'+rel.as_posix())
            add('profiles/'+agent_id+'/'+rel.as_posix(),text.encode(),p)
    # Global skill instructions are configuration only; executable helpers are not exported.
    for directory in ('skills','plugin-skills'):
        root=source/directory
        if root.is_dir():
            for p in regular_files(root,'*.md'):
                if p.is_symlink() or p.stat().st_size>2_000_000:continue
                rel=p.resolve().relative_to(root)
                if any(x.startswith('.') for x in rel.parts):continue
                text,n=clean_text(p.read_text(encoding='utf-8-sig'))
                if n:redactions.append('text:global/'+rel.as_posix())
                add('capability-reference/'+directory+'/'+rel.as_posix(),text.encode(),p)
    summary=dict(sourceVersion=config.get('meta',{}).get('lastTouchedVersion'),targetVersion='2026.9.7',sourceSchema='agents.entries (customized Windows setup)',profiles=profiles,importPolicy='Reference data only. Do not replace live config, activate capabilities, execute scripts, or inherit execution permissions automatically.',excluded=['Credential stores, secret files, browser/device identities, environment files, private keys','Conversation sessions, daily history, live SQLite databases, Git metadata','Model weights, media, runtime binaries and executable helpers'],redactedFields=redactions)
    summary['excludedReferences']=skipped
    add('migration-reference.json',(json.dumps(summary,indent=2,ensure_ascii=False)+'\n').encode(),source)
    manifest=dict(files=inventory,profiles=[dict(id=p['id'],name=p['name']) for p in profiles],redactionCount=len(redactions),note='Private export. Known credential values/patterns redacted; free-form notes require migration review. No automatic import.')
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    bundle=destination/'argos-nyx-proteus-config.zip'
    with zipfile.ZipFile(bundle,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
    # Verify contents and manifest hashes without printing personal text.
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:raise ValueError('Archive CRC validation failed')
        for item in inventory:
            if hashlib.sha256(archive.read(item['path'])).hexdigest()!=item['sha256']:raise ValueError('Manifest validation failed')
    digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
    (destination/'SHA256SUMS').write_text(digest+'  '+bundle.name+'\n')
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'README.txt').write_text('PRIVATE CONFIGURATION EXPORT\nCredentials and executable helpers excluded. Archive contents are inert reference data, not a ready-to-install Linux configuration. Review model/runtime/path compatibility and capability permissions before restoring. Keep in private storage; transfer over verified SSH.\n')
    print(json.dumps(dict(bundle=str(bundle),bytes=bundle.stat().st_size,sha256=digest,profiles=manifest['profiles'],fileCount=len(files),redactionCount=len(redactions))))

if __name__=='__main__':export(*sys.argv[1:])
