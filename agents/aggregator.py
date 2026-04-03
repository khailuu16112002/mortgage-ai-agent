"""Aggregator — tổng hợp kết quả 4 domain và in báo cáo cuối."""
from rich.console import Console
from rich.table import Table
from rich import box
from agents.state import GraphState, AgentResult

console = Console()

STATUS_ICON  = {"pass":"✅ PASS","missing":"⚠  MISSING","mismatch":"❌ FAIL","pending":"⏳"}
STATUS_COLOR = {"pass":"green","missing":"yellow","mismatch":"red","pending":"white"}


def aggregator_node(state: GraphState) -> GraphState:
    console.rule("[bold white]📊 AGGREGATOR — BÁO CÁO CUỐI[/bold white]")

    results: list[AgentResult] = [
        state.borrower_result,
        state.asset_result,
        state.employment_result,
        state.reo_result,
    ]

    all_missing    = [d for r in results for d in r.missing_docs]
    all_mismatches = [m for r in results for m in r.mismatches]
    all_notes      = [n for r in results for n in r.notes]
    all_pass       = not all_missing and not all_mismatches

    # ── Summary table ──────────────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Domain",     style="white",  width=22)
    table.add_column("Status",     width=14)
    table.add_column("Findings",   width=10, justify="right")
    table.add_column("Missing",    width=8,  justify="right")
    table.add_column("Mismatches", width=11, justify="right")

    domain_labels = {
        "borrower":          "Borrower",
        "assets":            "Assets",
        "employment":        "Employment",
        "real_estate_owned": "Real Estate Owned",
    }

    for r in results:
        c = STATUS_COLOR.get(r.status, "white")
        table.add_row(
            domain_labels.get(r.domain, r.domain),
            f"[{c}]{STATUS_ICON.get(r.status,'?')}[/{c}]",
            str(len(r.findings)),
            str(len(r.missing_docs)),
            str(len(r.mismatches)),
        )
    console.print(table)

    # ── Missing documents ──────────────────────────────────────────────────────
    if all_missing:
        console.print("\n[bold yellow]📭 TÀI LIỆU CẦN BỔ SUNG:[/bold yellow]")
        for i, d in enumerate(all_missing, 1):
            console.print(f"  [yellow]{i:2d}. {d}[/yellow]")

    # ── Data mismatches ────────────────────────────────────────────────────────
    if all_mismatches:
        console.print("\n[bold red]❌ DỮ LIỆU KHÔNG KHỚP:[/bold red]")
        for i, m in enumerate(all_mismatches, 1):
            console.print(f"  [red]{i:2d}. {m}[/red]")

    # ── Notes ─────────────────────────────────────────────────────────────────
    if all_notes:
        console.print("\n[bold dim]📝 GHI CHÚ:[/bold dim]")
        for n in all_notes:
            console.print(f"  [dim]• {n}[/dim]")

    # ── Field-level detail per domain ─────────────────────────────────────────
    console.print("\n[bold]🔍 CHI TIẾT TỪNG TRƯỜNG:[/bold]")
    for r in results:
        if not r.findings:
            continue
        label = domain_labels.get(r.domain, r.domain)
        console.print(f"\n  [cyan][{label}][/cyan]")
        for f in r.findings:
            sym = "[yellow]?[/yellow]" if f.is_missing else \
                  "[green]✓[/green]" if f.matched else "[red]✗[/red]"
            console.print(
                f"    {sym} {f.field_name:<45} "
                f"XML: {f.xml_value:<28} "
                f"PDF: {f.pdf_value}"
            )

    # ── Final verdict ──────────────────────────────────────────────────────────
    console.rule()
    if all_pass:
        console.print("[bold green]🎉 KẾT LUẬN: TẤT CẢ VALIDATION PASS — Hồ sơ hợp lệ[/bold green]")
    else:
        console.print(
            f"[bold red]⚠  KẾT LUẬN: {len(all_missing) + len(all_mismatches)} VẤN ĐỀ[/bold red]"
            f" — Thiếu: {len(all_missing)} tài liệu | Sai lệch: {len(all_mismatches)} trường"
        )
    console.rule()

    state.all_pass    = all_pass
    state.final_report = (
        f"{'PASS' if all_pass else 'FAIL'} | "
        f"Missing: {len(all_missing)} | Mismatches: {len(all_mismatches)}"
    )
    return state
