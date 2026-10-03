#!/usr/bin/env python3
"""Plan bounded ISO boot-menu edits without opening or writing a physical device."""
import base64, hashlib, json, pathlib, re, struct, sys

def locate(f, path):
    f.seek(16*2048); pvd=f.read(2048)
    if pvd[:7] != b'\x01CD001\x01': raise ValueError('ISO9660 primary descriptor missing')
    record=pvd[156:]
    for part in path.strip('/').split('/'):
        extent,size=struct.unpack_from('<I',record,2)[0],struct.unpack_from('<I',record,10)[0]
        f.seek(extent*2048); directory=f.read(size); pos=0; found=None
        while pos<len(directory):
            length=directory[pos]
            if not length: pos=((pos//2048)+1)*2048; continue
            entry=directory[pos:pos+length]; name=entry[33:33+entry[32]].decode('ascii',errors='replace').split(';')[0]
            if name.upper()==part.upper(): found=entry; break
            pos+=length
        if found is None: raise ValueError('ISO path missing: '+path)
        record=found
    offset=struct.unpack_from('<I',record,2)[0]*2048
    size=struct.unpack_from('<I',record,10)[0]
    f.seek(offset); return offset,f.read(size)

def menu(old,hook=False):
    text=old.decode()
    kernel=re.search(r'^\s*linux\s+(\S+)',text,re.M).group(1)
    initrd=re.search(r'^\s*initrd\s+(\S+)',text,re.M).group(1)
    base='boot=live components persistence persistence-encryption=luks persistence-media=removable-usb username=argos hostname=argos-live console=tty0'
    if hook: base+=' live-config.hooks=file:///run/live/medium/live/filesystem.packages'
    choices=[('Argos diagnostics - text, GPU disabled','nomodeset module_blacklist=nouveau,nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm systemd.unit=multi-user.target systemd.show_status=1'),('Argos desktop',''),('Argos desktop - basic graphics','nomodeset')]
    result='source /boot/grub/config.cfg\nset default=0\nset timeout=-1\n'
    for name,args in choices:
        result+=f'menuentry "{name}" {{\n linux {kernel} {base} {args}\n initrd {initrd}\n}}\n'
    encoded=result.encode()
    if len(encoded)>len(old): raise ValueError('Menu does not fit existing file allocation')
    return encoded+b' '*(len(old)-len(encoded))

def plan(source,previous=None,payload=None):
    prior=json.loads(pathlib.Path(previous).read_text())['segments'] if previous else []
    def current(offset,data):
        result=bytearray(data)
        for s in prior:
            a=max(offset,s['offset']); b=min(offset+len(data),s['offset']+s['length'])
            if a<b: result[a-offset:b-offset]=base64.b64decode(s['after'])[a-s['offset']:b-s['offset']]
        return bytes(result)
    with open(source,'rb') as f:
        offset,old=locate(f,'/boot/grub/grub.cfg'); old=current(offset,old); new=menu(old,hook=payload is not None)
        changes=[(offset,old,new,'GRUB menu')]
        md_offset,md_old=locate(f,'/sha256sum.txt')
        md_old=current(md_offset,md_old)
        replacements={b'boot/grub/grub.cfg':(old,new)}
        if payload:
            package_offset,package_old=locate(f,'/live/filesystem.packages')
            package_old=current(package_offset,package_old); package_new=pathlib.Path(payload).read_bytes()
            if len(package_new)>len(package_old): raise ValueError('Access hook exceeds existing allocation')
            package_new+=b' '*(len(package_old)-len(package_new))
            changes.append((package_offset,package_old,package_new,'Owner access setup hook'))
            replacements[b'live/filesystem.packages']=(package_old,package_new)
        lines=md_old.splitlines(keepends=True); hits=0
        for i,line in enumerate(lines):
            for name,(before,after) in replacements.items():
                if line.rstrip().endswith(name):
                    if line[:64]!=hashlib.sha256(before).hexdigest().encode(): raise ValueError('Boot-file checksum mismatch')
                    lines[i]=hashlib.sha256(after).hexdigest().encode()+line[64:]; hits+=1
        if hits!=len(replacements): raise ValueError('Unique boot checksum entries required')
        changes.append((md_offset,md_old,b''.join(lines),'Boot checksum manifest'))
        segments=[]
        for offset,old,new,label in changes:
            start=offset//512*512; end=(offset+len(old)+511)//512*512
            f.seek(start); before=current(start,f.read(end-start)); after=bytearray(before)
            after[offset-start:offset-start+len(old)]=new
            if start<34*512 or end>=4233101312: raise ValueError('Patch outside safe boot region')
            segments.append(dict(offset=start,length=len(before),before=base64.b64encode(before).decode(),after=base64.b64encode(after).decode(),label=label))
    return dict(serial='0B8F640168E7',capacity=31474057216,uniqueId='USBSTOR\\DISK&VEN_KINGSTON&PROD_DATATRAVELER_3.0&REV_PMAP\\08606E694934BF418705FC70&0:Toronado',persistenceStart=4233101312,segments=segments)

if __name__=='__main__':
    source,out=sys.argv[1:3]
    result=plan(source,*sys.argv[3:])
    pathlib.Path(out).write_text(json.dumps(result,indent=2))
    print('Prepared boot-only patch:',[(s['label'],s['offset'],s['length']) for s in result['segments']])
