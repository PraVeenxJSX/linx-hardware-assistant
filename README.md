# Local Linux Hardware Q&A Assistant

Problem 2 implementation. A local CLI assistant that gathers real machine facts through a fixed allow-list of read-only Linux utilities, normalizes outputs, caches context, and answers without guessing.

## Requirements
- Linux laptop (the assignment explicitly targets Linux)
- Python 3.11+
- Optional: Ollama + `qwen2.5:7b` for natural-language synthesis
- Optional: `lscpu`, `free`, `lsblk`, `lspci`, `dmidecode`, `nvidia-smi`

## Install and run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m hardware_assistant.cli capabilities
python -m hardware_assistant.cli chat
```
If the module entrypoint is not found in your environment, run `python -m hardware_assistant.cli chat` from this project directory.

## Example questions
- How much RAM do I have?
- Can I add more RAM, and how many slots are free?
- What CPU and architecture does this machine use?
- Is my SSD NVMe?
- What GPU is installed?

## Safety model
- With Ollama enabled, the model may select only named, schema-defined inspection functions; returned names are checked against the fixed registry before execution. Without Ollama, a conservative local intent router is used. LLM/user input never becomes a command or shell string.
- Tool names map to fixed binary names and fixed argument arrays.
- `subprocess.run(..., shell=False)`; bounded timeout; controlled environment; read-only commands only.
- `dmidecode` is attempted through non-interactive sudo only, never by running the whole app as root. Configure a narrowly scoped sudoers entry only after reviewing your distro's exact binary path and security policy. If unavailable, the app reports the limitation.
- Missing utilities are detected and reported; no invented hardware facts.

## Accuracy and limitations
- OS-visible RAM (`free`) is not the same as firmware-reported maximum RAM capacity.
- Slot count and maximum capacity depend on `dmidecode` permissions and firmware tables; if unavailable, the assistant says so.
- NVMe is inferred from the device transport reported by `lsblk`; some systems expose transport differently.
- NVIDIA details require `nvidia-smi`; other GPUs are identified from PCI display-controller entries where possible.
- This project runs the inspection tools on Linux. Windows is not a supported host for the assignment's Linux-specific collectors.

## Local model (optional)
Install Ollama separately, pull a compatible model, then set `OLLAMA_ENABLED=true` in `.env`. Hardware JSON is sent only to the local Ollama endpoint. With Ollama disabled, all responses are deterministic and offline.

## Tests
```bash
pytest -q
```

## Final hardening (Problem 2)

- Ollama receives only tools whose utilities are found in trusted system directories or whose documented `/proc`/`/sys` fallback exists.
- CPU and memory collectors fall back to `/proc/cpuinfo` and `/proc/meminfo`; block devices and PCI inventory fall back to `/sys`.
- `/sys/class/dmi/id` may identify the board/system, but does not reliably expose DIMM slots or maximum supported RAM. Those values remain unknown unless `dmidecode` provides them.
- NVIDIA CSV is normalized into `data.gpus[]` records with model, VRAM and driver version.
- Hardware facts are cached for the CLI session and reused for follow-up questions.
- Ollama can select tools, but its generated prose is not trusted to assert hardware specifications; the deterministic answer based on collected facts remains authoritative.
- Executables are resolved only from `/usr/bin`, `/bin`, `/usr/sbin`, and `/sbin`; fixed arguments, `shell=False`, and timeouts are retained.

Run all tests from the project directory:
```bash
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```
