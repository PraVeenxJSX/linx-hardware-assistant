"""Safe, read-only Linux hardware collectors with procfs/sysfs fallbacks."""
import csv, io, json, os, re, shlex, shutil, subprocess
from pathlib import Path

TRUSTED_BIN_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
COMMANDS = {
    "cpu": ("lscpu", []), "memory": ("free", ["-b"]),
    "block_devices": ("lsblk", ["-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA,TRAN,FSTYPE"]),
    "filesystem_usage": ("df", ["-B1", "--output=source,fstype,size,used,avail,pcent,target"]),
    "pci": ("lspci", ["-mm"]), "dmi_memory": ("dmidecode", ["--type", "memory"]),
    "gpu_nvidia": ("nvidia-smi", ["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
}

def _which(binary):
    p = shutil.which(binary, path=":".join(TRUSTED_BIN_DIRS))
    if not p: return None
    p = os.path.realpath(p)
    if not any(p.startswith(d + os.sep) for d in TRUSTED_BIN_DIRS): return None
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None

def _err(message, kind): return {"available": False, "error": str(message)[:400], "error_type": kind}

def format_bytes(value):
    try: n = float(value)
    except (TypeError, ValueError, OverflowError): return "size unknown"
    if n < 0: return "size unknown"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if n < 1024 or unit == "PiB": return f"{int(n)} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024

def available_tools():
    d = {k: _which(v[0]) is not None for k, v in COMMANDS.items()}
    d["cpu"] |= Path('/proc/cpuinfo').is_file()
    d["memory"] |= Path('/proc/meminfo').is_file()
    d["block_devices"] |= Path('/sys/block').is_dir()
    d["pci"] |= Path('/sys/bus/pci/devices').is_dir()
    d["dmi_memory"] |= Path('/sys/class/dmi/id').is_dir()
    return d

def _run_fixed(name, timeout=5):
    if name not in COMMANDS: raise ValueError("Tool is not allow-listed")
    binary, args = COMMANDS[name]; path = _which(binary)
    if not path: return _err(f"Required utility '{binary}' is not installed in trusted system paths.", "missing_executable")
    cmd = [path, *args]
    if name == 'dmi_memory' and hasattr(os, 'geteuid') and os.geteuid() != 0:
        sudo = _which('sudo')
        if not sudo: return _err('dmidecode requires root; sudo is unavailable.', 'permission')
        cmd = [sudo, '-n', path, *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, shell=False,
                           close_fds=True, env={'PATH': ':'.join(TRUSTED_BIN_DIRS), 'LANG':'C', 'LC_ALL':'C'})
        if r.returncode:
            msg = (r.stderr or r.stdout or 'Command failed').strip(); low = msg.lower()
            typ = 'permission' if any(x in low for x in ('permission denied','must be root','operation not permitted','not permitted')) else 'command_failed'
            return _err(msg, typ)
        return {'available': True, 'stdout': r.stdout}
    except subprocess.TimeoutExpired: return _err(f'{name} timed out after {timeout}s.', 'timeout')
    except PermissionError as e: return _err(f'Permission denied: {e}', 'permission')
    except FileNotFoundError: return _err(f'{binary} could not be started.', 'missing_executable')
    except OSError as e: return _err(str(e), 'execution_error')

def parse_cpu(raw):
    d={}
    for line in raw.splitlines():
        if ':' in line:
            k,v=line.split(':',1); d[k.strip().lower().replace(' ','_')]=v.strip()
    return {'model':d.get('model_name') or d.get('hardware'),'architecture':d.get('architecture'),
            'logical_cpus':d.get('cpu(s)'),'cores_per_socket':d.get('core(s)_per_socket'),
            'sockets':d.get('socket(s)'),'max_mhz':d.get('cpu_max_mhz'),'vendor':d.get('vendor_id'),'raw_fields':d}

def parse_proc_cpuinfo(raw):
    d={}
    for line in raw.splitlines():
        if ':' in line:
            k,v=line.split(':',1); d.setdefault(k.strip().lower(),v.strip())
    count=sum(x.lower().startswith('processor') for x in raw.splitlines())
    return {'model':d.get('model name') or d.get('hardware') or d.get('processor'),'architecture':d.get('isa') or d.get('cpu architecture'),
            'logical_cpus':count or None,'cores_per_socket':None,'sockets':None,'max_mhz':None,'vendor':d.get('vendor_id'),'source':'/proc/cpuinfo'}

def parse_memory(raw):
    for line in raw.splitlines():
        row=line.split()
        if row and row[0].lower()=='mem:' and len(row)>=4:
            try: total,used,free=map(int,row[1:4])
            except ValueError: return {'error':'Could not parse numeric values in free output'}
            return {'total_bytes':total,'used_bytes':used,'free_bytes':free,'total_gib':round(total/1024**3,2)}
    return {'error':'Could not parse free output'}

def parse_proc_meminfo(raw):
    d={}
    for line in raw.splitlines():
        m=re.match(r'^(MemTotal|MemAvailable|MemFree):\s+(\d+)\s+kB$',line)
        if m: d[m.group(1)]=int(m.group(2))*1024
    total=d.get('MemTotal')
    if total is None: return {'error':'MemTotal missing from /proc/meminfo'}
    free=d.get('MemAvailable',d.get('MemFree'))
    return {'total_bytes':total,'used_bytes':max(0,total-free) if free is not None else None,'free_bytes':free,'total_gib':round(total/1024**3,2),'source':'/proc/meminfo'}

def parse_block_devices(raw):
    try: d=json.loads(raw)
    except (ValueError,TypeError): return {'error':'lsblk returned invalid JSON'}
    if not isinstance(d,dict) or not isinstance(d.get('blockdevices'),list): return {'error':'lsblk JSON missing blockdevices list'}
    out=[]
    def walk(items):
        for x in items:
            if not isinstance(x,dict): continue
            size=x.get('size'); out.append({'name':x.get('name'),'size_bytes':size,'size_human':format_bytes(size),'type':x.get('type'),
                'mountpoint':x.get('mountpoint'),'model':(x.get('model') or '').strip() or None,'transport':x.get('tran'),
                'filesystem':x.get('fstype'),'rotational':x.get('rota')})
            if isinstance(x.get('children'),list): walk(x['children'])
    walk(d['blockdevices']); return {'devices':out}

def parse_sys_block():
    root=Path('/sys/block'); out=[]
    if not root.is_dir(): return {'error':'/sys/block unavailable'}
    for p in sorted(root.iterdir()):
        try: size=int((p/'size').read_text().strip())*512
        except (OSError,ValueError): size=None
        def read(rel):
            try: return (p/rel).read_text().strip() or None
            except OSError: return None
        rot=read('queue/rotational')
        out.append({'name':p.name,'size_bytes':size,'size_human':format_bytes(size),'type':'disk','mountpoint':None,
                    'model':read('device/model'),'transport':None,'filesystem':None,'rotational':bool(int(rot)) if rot in ('0','1') else None,'source':'/sys/block'})
    return {'devices':out}

def parse_filesystem_usage(raw):
    rows=[]
    for line in [x.strip() for x in raw.splitlines() if x.strip()][1:]:
        c=line.split(None,6)
        if len(c)!=7: continue
        src,fs,size,used,avail,pct,mount=c
        try: size,used,avail=map(int,(size,used,avail))
        except ValueError: continue
        rows.append({'source':src,'filesystem_type':fs,'size_bytes':size,'used_bytes':used,'available_bytes':avail,
                     'size_human':format_bytes(size),'used_human':format_bytes(used),'available_human':format_bytes(avail),'use_percent':pct,'mountpoint':mount})
    return {'filesystems':rows} if rows else {'filesystems':[],'error':'No parseable filesystem rows'}

def parse_dmi_memory(raw):
    devices=[]; maximum=None; cur=None
    for line in raw.splitlines():
        t=line.strip()
        if t.startswith('Maximum Capacity:'): maximum=t.split(':',1)[1].strip()
        elif t.startswith('Memory Device'):
            if cur is not None: devices.append(cur)
            cur={}
        elif ':' in t and cur is not None:
            k,v=t.split(':',1); cur[k.strip().lower().replace(' ','_')]=v.strip()
    if cur is not None: devices.append(cur)
    mods=[x for x in devices if x.get('size','').lower() not in ('no module installed','unknown','')]
    return {'maximum_capacity':maximum,'total_slots':len(devices),'used_slots':len(mods),'free_slots':max(0,len(devices)-len(mods)),
            'installed_modules':[{'size':x.get('size'),'type':x.get('type'),'speed':x.get('speed'),'locator':x.get('locator')} for x in mods]}

def parse_sys_dmi():
    root=Path('/sys/class/dmi/id')
    if not root.is_dir(): return {'error':'DMI sysfs unavailable'}
    fields={}
    for k in ('sys_vendor','product_name','board_vendor','board_name','bios_vendor','bios_version'):
        try: fields[k]=(root/k).read_text().strip()
        except OSError: pass
    return {'maximum_capacity':None,'total_slots':None,'used_slots':None,'free_slots':None,'installed_modules':[],
            'system_identity':fields,'source':'/sys/class/dmi/id','note':'sysfs does not reliably expose DIMM slot population or maximum memory capacity.'}

def parse_pci(raw):
    devices=[]; classes={'vga compatible controller','3d controller','display controller'}
    for line in raw.splitlines():
        line=line.strip()
        if not line: continue
        try: f=shlex.split(line)
        except ValueError: f=[]
        if len(f)>=4:
            a,c,v,d=f[:4]; devices.append({'address':a,'class':c,'vendor':v,'device':d,'subsystem':' '.join(f[4:]) or None})
        else: devices.append({'raw':line})
    return {'devices':devices,'gpu_controllers':[x for x in devices if x.get('class','').lower() in classes]}

def parse_sys_pci():
    root=Path('/sys/bus/pci/devices'); devices=[]
    if not root.is_dir(): return {'error':'PCI sysfs unavailable'}
    names={'0300':'VGA compatible controller','0302':'3D controller','0380':'Display controller'}
    for p in sorted(root.iterdir()):
        try:
            cls=(p/'class').read_text().strip().removeprefix('0x'); ven=(p/'vendor').read_text().strip(); dev=(p/'device').read_text().strip()
        except OSError: continue
        devices.append({'address':p.name,'class':names.get(cls[-4:],f'PCI class {cls}'),'vendor_id':ven,'device_id':dev,'source':'/sys/bus/pci/devices'})
    return {'devices':devices,'gpu_controllers':[x for x in devices if x.get('class','').startswith(('VGA','3D','Display'))]}

def parse_nvidia_csv(raw):
    rows=[]
    for row in csv.reader(io.StringIO(raw)):
        if not row: continue
        if len(row)<3: return {'error':'nvidia-smi returned malformed CSV'}
        rows.append({'name':row[0].strip(),'memory_total':row[1].strip(),'driver_version':row[2].strip()})
    return {'gpus':rows,'source':'nvidia-smi'} if rows else {'error':'nvidia-smi returned no GPU rows'}

def inspect(name):
    if name not in COMMANDS: raise ValueError('Tool is not allow-listed')
    r=_run_fixed(name)
    if r.get('available'):
        parsers={'cpu':parse_cpu,'memory':parse_memory,'block_devices':parse_block_devices,'filesystem_usage':parse_filesystem_usage,
                 'pci':parse_pci,'dmi_memory':parse_dmi_memory,'gpu_nvidia':parse_nvidia_csv}
        try: d=parsers[name](r.get('stdout',''))
        except (ValueError,TypeError,KeyError,IndexError,AttributeError) as e: d={'error':str(e)}
        if not d.get('error'): return {'available':True,'data':d}
        r=_err(d['error'],'malformed_output')
    fallback=None
    try:
        if name=='cpu': fallback=parse_proc_cpuinfo(Path('/proc/cpuinfo').read_text())
        elif name=='memory': fallback=parse_proc_meminfo(Path('/proc/meminfo').read_text())
        elif name=='block_devices': fallback=parse_sys_block()
        elif name=='pci': fallback=parse_sys_pci()
        elif name=='dmi_memory': fallback=parse_sys_dmi()
    except OSError: pass
    if fallback and not fallback.get('error'):
        return {'available':True,'data':fallback,'fallback_used':True,'primary_error':r.get('error'),'primary_error_type':r.get('error_type')}
    return r
