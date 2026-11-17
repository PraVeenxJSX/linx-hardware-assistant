from hardware_assistant.collectors import parse_memory, parse_block_devices, parse_dmi_memory
from hardware_assistant.assistant import HardwareAssistant

def test_parse_memory():
    result=parse_memory("              total        used        free\nMem:     17179869184 4294967296 12884901888")
    assert result["total_gib"]==16.0

def test_parse_lsblk_json():
    result=parse_block_devices('{"blockdevices":[{"name":"nvme0n1","size":512000,"type":"disk","tran":"nvme"}]}')
    assert result["devices"][0]["transport"]=="nvme"

def test_dmi_slots():
    raw="Memory Device\n Size: 16 GB\n Type: DDR4\nMemory Device\n Size: No Module Installed\n"
    result=parse_dmi_memory(raw)
    assert result["used_slots"]==1 and result["free_slots"]==1

def test_tool_selection():
    a=HardwareAssistant(use_ollama=False)
    assert "cpu" in a.select_tools("What CPU do I have?")
    assert "block_devices" in a.select_tools("Is my SSD NVMe?")


def test_parse_pci_machine_readable_gpu():
    from hardware_assistant.collectors import parse_pci
    raw = '27a3:00:00.0 "3D controller" "Microsoft Corporation" "Basic Render Driver" -p00 "" ""\n'
    result = parse_pci(raw)
    gpu = result["gpu_controllers"][0]
    assert gpu["vendor"] == "Microsoft Corporation"
    assert gpu["device"] == "Basic Render Driver"
    assert gpu["class"] == "3D controller"


def test_format_storage_size():
    from hardware_assistant.collectors import format_bytes
    assert format_bytes(1099511627776) == "1.00 TiB"
