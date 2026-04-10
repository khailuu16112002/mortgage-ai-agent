"""
Supervisor Agent — parse XML baseline + phân loại PDF files.
"""
from pathlib import Path
from rich.console import Console
from agents.state import GraphState
from utils.xml_parser import parse_xml
from utils.file_classifier import classify_directory, print_classification

console = Console()


def supervisor_node(state: GraphState) -> GraphState:
    console.rule("[bold cyan]🧠 SUPERVISOR AGENT[/bold cyan]")

    # 1. Parse XML → XMLBaseline dataclass
    console.print(f"[cyan]→ Parse XML:[/cyan] {state.xml_path}")
    try:
        state.baseline = parse_xml(state.xml_path)
    except Exception as e:
        console.print(f"[red]✗ Lỗi parse XML: {e}[/red]")
        raise

    # 2. Export JSON baseline + build flat facts for agent comparison
    out_dir = Path(state.xml_path).parent
    from utils.xml_to_json import save_baseline_json, save_flat_facts, baseline_to_flat_facts
    try:
        save_baseline_json(state.baseline, str(out_dir / "baseline.json"))
        save_flat_facts(state.baseline,    str(out_dir / "baseline_facts.json"))
        state.flat_facts = baseline_to_flat_facts(state.baseline)
        console.print(f"[dim]✓ JSON exports: baseline.json + baseline_facts.json ({len(state.flat_facts)} facts)[/dim]")
    except Exception as e:
        console.print(f"[yellow]⚠ Không lưu được JSON: {e}[/yellow]")

    # 3. Classify PDFs → map vào 4 domain
    console.print(f"\n[cyan]→ Phân loại PDFs:[/cyan] {state.pdf_dir}")
    state.classified_files = classify_directory(state.pdf_dir)
    print_classification(state.classified_files)

    total = sum(len(v) for v in state.classified_files.values())
    console.print(f"\n[green]✓ Supervisor xong:[/green] {total} PDFs → giao 4 sub-agents")
    console.rule()
    return state
