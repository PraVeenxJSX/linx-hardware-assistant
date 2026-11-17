import asyncio
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from .assistant import HardwareAssistant
from .collectors import available_tools

app=typer.Typer(help="Private, read-only Linux hardware Q&A assistant.")
console=Console()

@app.command()
def capabilities():
    """Show which fixed inspection utilities are installed."""
    for name,ok in available_tools().items():
        console.print(f"{'✓' if ok else '—'} {name}: {'available' if ok else 'not available'}")

@app.command()
def chat():
    """Start an interactive hardware Q&A session."""
    assistant=HardwareAssistant()
    console.print(Panel("Local Linux Hardware Assistant\nType 'exit' to quit. No shell commands are accepted from chat."))
    while True:
        q=Prompt.ask("[bold cyan]You[/bold cyan]")
        if q.strip().lower() in {"exit","quit"}: break
        result=asyncio.run(assistant.ask(q))
        console.print(Panel(result["answer"],title="Hardware Assistant"))
        checked = result.get("tools_used", [])
        unavailable = result.get("tools_unavailable", {})
        successful = [name for name in checked if name not in unavailable]
        if checked:
            console.print("[dim]Successful inspections: "+(", ".join(successful) or "none")+"[/dim]")
            if unavailable:
                details = "; ".join(f"{name}: {reason}" for name, reason in unavailable.items())
                console.print("[yellow]Attempted but unavailable: "+details+"[/yellow]")
        else:
            console.print("[dim]Inspections: none (answered from environment context or conversation)[/dim]")

if __name__=="__main__":
    app()
