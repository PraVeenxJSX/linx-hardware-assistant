import pytest
from hardware_assistant.assistant import HardwareAssistant



def test_environment_question_variants_are_recognized():
    phrases = [
        "Is this actual laptop hardware or Docker virtual hardware?",
        "Am I running inside Docker?",
        "Why is my RAM different from Windows?",
        "Are these physical or virtual disks?",
    ]
    assert all(HardwareAssistant._is_environment_question(q) for q in phrases)


def test_environment_question_uses_environment_answer_without_collectors(monkeypatch):
    import asyncio
    assistant = HardwareAssistant(use_ollama=False)
    monkeypatch.setattr(assistant, "_environment_explanation", lambda: "Docker environment confirmed")
    result = asyncio.run(assistant.ask("Is this actual laptop hardware or Docker virtual hardware?"))
    assert result["answer"] == "Docker environment confirmed"
    assert result["tools_used"] == []


def test_attempted_unavailable_tools_are_reported_separately(monkeypatch):
    import asyncio
    assistant = HardwareAssistant(use_ollama=False)
    monkeypatch.setattr(assistant, "select_tools", lambda q: ["cpu", "gpu_nvidia"])
    monkeypatch.setattr(assistant, "gather", lambda names: {
        "cpu": {"available": True, "data": {"model": "Example CPU"}},
        "gpu_nvidia": {"available": False, "error": "nvidia-smi missing"},
    })
    result = asyncio.run(assistant.ask("What CPU and NVIDIA GPU do I have?"))
    assert result["tools_used"] == ["cpu", "gpu_nvidia"]
    assert result["tools_unavailable"] == {"gpu_nvidia": "nvidia-smi missing"}
