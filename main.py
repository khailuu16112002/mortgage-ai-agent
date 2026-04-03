"""
Mortgage Verification Agent — Entry Point

Cách dùng:
    python main.py --xml data/Patrick_Durst.xml --pdfs data/pdfs/
    python main.py                          # interactive mode
"""
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()


def check_env():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key.startswith("sk-"):
        console.print(Panel(
            "[red]OPENAI_API_KEY chưa được set![/red]\n\n"
            "1. Copy file [cyan].env.example[/cyan] → [cyan].env[/cyan]\n"
            "2. Điền OpenAI API key vào [cyan].env[/cyan]\n"
            "3. Chạy lại",
            title="❌ Thiếu API Key", border_style="red"
        ))
        sys.exit(1)


def main():
    check_env()

    parser = argparse.ArgumentParser(description="Mortgage Verification Multi-Agent")
    parser.add_argument("--xml",  type=str, help="Đường dẫn XML baseline")
    parser.add_argument("--pdfs", type=str, help="Thư mục PDF documents")
    args = parser.parse_args()

    if args.xml and args.pdfs:
        xml_path, pdf_dir = args.xml, args.pdfs
    else:
        console.print(Panel(
            "🏦 [bold cyan]Mortgage Verification Agent[/bold cyan]\n"
            "[dim]LangGraph · MISMO 3.4 · 4 domains: borrower / assets / employment / real_estate_owned[/dim]",
            border_style="cyan"
        ))
        xml_path = console.input("\n📄 XML baseline path: ").strip()
        pdf_dir  = console.input("📂 PDF directory path: ").strip()

    if not Path(xml_path).exists():
        console.print(f"[red]✗ Không tìm thấy: {xml_path}[/red]"); sys.exit(1)
    if not Path(pdf_dir).is_dir():
        console.print(f"[red]✗ Không phải thư mục: {pdf_dir}[/red]"); sys.exit(1)

    from graph import build_graph

    initial = {
        "xml_path": xml_path, "pdf_dir": pdf_dir,
        "baseline": None, "flat_facts": {}, "classified_files": {},
        "borrower_result": None, "asset_result": None,
        "employment_result": None, "reo_result": None,
        "final_report": "", "all_pass": False,
    }

    final = build_graph().invoke(initial)
    sys.exit(0 if final.get("all_pass") else 1)


if __name__ == "__main__":
    main()
