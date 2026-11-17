import asyncio
import subprocess
from types import SimpleNamespace
import pytest
from hardware_assistant import collectors as c
from hardware_assistant.assistant import HardwareAssistant

def test_proc_meminfo_fallback_parser():
    d=c.parse_proc_meminfo('MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n')
    assert d['total_gib']==16.0 and d['source']=='/proc/meminfo'

def test_proc_cpuinfo_fallback_parser():
    d=c.parse_proc_cpuinfo('processor : 0\nmodel name : Example CPU\n')
    assert d['model']=='Example CPU' and d['logical_cpus']==1

def test_nvidia_csv_structured():
    d=c.parse_nvidia_csv('NVIDIA Example, 8192 MiB, 555.12\n')
    assert d['gpus'][0]['name']=='NVIDIA Example'
    assert d['gpus'][0]['memory_total']=='8192 MiB'

def test_nvidia_bad_csv():
    assert 'error' in c.parse_nvidia_csv('bad row')

def test_sys_dmi_never_invents_slots(monkeypatch, tmp_path):
    root=tmp_path/'id'; root.mkdir(); (root/'board_name').write_text('Example Board')
    original=c.Path
    monkeypatch.setattr(c, 'Path', lambda p: root if p=='/sys/class/dmi/id' else original(p))
    d=c.parse_sys_dmi()
    assert d['total_slots'] is None and d['maximum_capacity'] is None

def test_allowlist_and_shell_false(monkeypatch):
    with pytest.raises(ValueError): c._run_fixed('arbitrary')
    monkeypatch.setattr(c, '_which', lambda n: f'/usr/bin/{n}')
    seen={}
    def fake(cmd, **kw):
        seen['cmd']=cmd; seen.update(kw)
        return SimpleNamespace(returncode=0, stdout='Architecture: x86_64', stderr='')
    monkeypatch.setattr(c.subprocess, 'run', fake)
    assert c._run_fixed('cpu')['available']
    assert seen['shell'] is False and seen['cmd']==['/usr/bin/lscpu']

def test_missing_executable(monkeypatch):
    monkeypatch.setattr(c, '_which', lambda _: None)
    assert c._run_fixed('cpu')['error_type']=='missing_executable'

def test_permission_timeout(monkeypatch):
    monkeypatch.setattr(c, '_which', lambda n: f'/usr/bin/{n}')
    monkeypatch.setattr(c.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(PermissionError('denied')))
    assert c._run_fixed('cpu')['error_type']=='permission'
    def timeout(*a, **k): raise subprocess.TimeoutExpired('lscpu', 5)
    monkeypatch.setattr(c.subprocess, 'run', timeout)
    assert c._run_fixed('cpu')['error_type']=='timeout'

def test_gather_reuses_cached_data(monkeypatch):
    a=HardwareAssistant(use_ollama=False); calls=[]
    monkeypatch.setattr('hardware_assistant.assistant.inspect', lambda n: calls.append(n) or {'available':True,'data':{'model':'cached'}})
    assert a.gather(['cpu'])==a.gather(['cpu'])
    assert calls==['cpu']

def test_ollama_tool_registry_only_available(monkeypatch):
    a=HardwareAssistant(use_ollama=True)
    monkeypatch.setattr('hardware_assistant.assistant.available_tools', lambda: {
        'cpu':True,'memory':False,'block_devices':True,'filesystem_usage':False,
        'pci':False,'dmi_memory':False,'gpu_nvidia':False})
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'message':{'tool_calls':[{'function':{'name':'inspect_cpu'}}]}}
    class Client:
        def __init__(self,*a,**k): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def post(self,url,json):
            names=[x['function']['name'] for x in json['tools']]
            assert names==['inspect_cpu','inspect_block_devices']
            return Response()
    import httpx
    monkeypatch.setattr(httpx,'AsyncClient',Client)
    assert asyncio.run(a._llm_select_tools('CPU?'))==['cpu']

def test_df_mountpoint_spaces():
    raw='Filesystem Type 1B-blocks Used Available Use% Mounted on\n/dev/sda1 ext4 1000 200 800 20% /mnt/my drive\n'
    assert c.parse_filesystem_usage(raw)['filesystems'][0]['mountpoint']=='/mnt/my drive'
