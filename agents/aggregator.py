"""Aggregator — tổng hợp kết quả 4 domain và in báo cáo cuối.

FIX:
- Separate sections: PASS fields, FAIL fields, MISSING fields
- Field detail table rõ ràng với alignment và icon
- Summary counts phân biệt pass/fail/missing per domain
- Total counts ở cuối
"""
from rich.console import Console
from rich.table import Table
from rich import box
from agents.state import GraphState, AgentResult, ValidationFinding

console = Console()

STATUS_ICON  = {"pass": "✅ PASS", "missing": "⚠  MISSING", "mismatch": "❌ FAIL", "pending": "⏳"}
STATUS_COLOR = {"pass": "green",   "missing": "yellow",      "mismatch": "red",      "pending": "white"}


def _finding_icon(f: ValidationFinding) -> str:
    if f.is_missing:
        return "[yellow]⚠ MISS[/yellow]"
    if f.matched:
        return "[green]  ✓[/green]"
    return "[red]  ✗[/red]"


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

    domain_labels = {
        "borrower":          "Borrower",
        "assets":            "Assets",
        "employment":        "Employment",
        "real_estate_owned": "Real Estate Owned",
    }

    # ── Domain summary table ───────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Domain",     style="white",  width=22)
    table.add_column("Status",     width=14)
    table.add_column("✓ Pass",     width=8,  justify="right")
    table.add_column("✗ Fail",     width=8,  justify="right")
    table.add_column("⚠ Missing",  width=10, justify="right")
    table.add_column("Total",      width=8,  justify="right")

    for r in results:
        c     = STATUS_COLOR.get(r.status, "white")
        n_ok  = sum(1 for f in r.findings if f.matched and not f.is_missing)
        n_bad = sum(1 for f in r.findings if not f.matched and not f.is_missing)
        n_mis = sum(1 for f in r.findings if f.is_missing)
        table.add_row(
            domain_labels.get(r.domain, r.domain),
            f"[{c}]{STATUS_ICON.get(r.status,'?')}[/{c}]",
            f"[green]{n_ok}[/green]",
            f"[red]{n_bad}[/red]" if n_bad else "0",
            f"[yellow]{n_mis}[/yellow]" if n_mis else "0",
            str(len(r.findings)),
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

        # Group: FAIL + MISSING first, then PASS
        fail_fields    = [f for f in r.findings if not f.matched and not f.is_missing]
        missing_fields = [f for f in r.findings if f.is_missing]
        pass_fields    = [f for f in r.findings if f.matched and not f.is_missing]

        console.print(f"\n  [cyan][{label}][/cyan]  "
                      f"[green]{len(pass_fields)} pass[/green] | "
                      f"[red]{len(fail_fields)} fail[/red] | "
                      f"[yellow]{len(missing_fields)} missing[/yellow]")

        # Print fails first (most important)
        if fail_fields:
            console.print("  [bold red]  ── FAIL ──[/bold red]")
            for f in fail_fields:
                console.print(
                    f"    [red]✗[/red] {f.field_name:<52} "
                    f"[dim]XML:[/dim] {str(f.xml_value):<30} "
                    f"[dim]PDF:[/dim] [red]{f.pdf_value}[/red]"
                )

        if missing_fields:
            console.print("  [bold yellow]  ── MISSING ──[/bold yellow]")
            for f in missing_fields:
                console.print(
                    f"    [yellow]⚠[/yellow] {f.field_name:<52} "
                    f"[dim]XML:[/dim] {str(f.xml_value):<30} "
                    f"[dim]PDF:[/dim] [yellow]{f.pdf_value}[/yellow]"
                )

        if pass_fields:
            console.print("  [bold green]  ── PASS ──[/bold green]")
            for f in pass_fields:
                console.print(
                    f"    [green]✓[/green] {f.field_name:<52} "
                    f"[dim]XML:[/dim] {str(f.xml_value):<30} "
                    f"[dim]PDF:[/dim] {f.pdf_value}"
                )

    # ── Overall totals ─────────────────────────────────────────────────────────
    total_findings = sum(len(r.findings) for r in results)
    total_ok  = sum(sum(1 for f in r.findings if f.matched and not f.is_missing) for r in results)
    total_bad = sum(sum(1 for f in r.findings if not f.matched and not f.is_missing) for r in results)
    total_mis = sum(sum(1 for f in r.findings if f.is_missing) for r in results)

    console.rule()
    console.print(
        f"[bold]TOTALS:[/bold] {total_findings} fields checked — "
        f"[green]{total_ok} pass[/green] | "
        f"[red]{total_bad} fail[/red] | "
        f"[yellow]{total_mis} missing[/yellow]"
    )

    # ── Final verdict ──────────────────────────────────────────────────────────
    if all_pass:
        console.print("[bold green]🎉 KẾT LUẬN: TẤT CẢ VALIDATION PASS — Hồ sơ hợp lệ[/bold green]")
    else:
        n_issues = len(all_missing) + len(all_mismatches)
        console.print(
            f"[bold red]⚠  KẾT LUẬN: {n_issues} VẤN ĐỀ[/bold red]"
            f" — Thiếu: {len(all_missing)} tài liệu | Sai lệch: {len(all_mismatches)} trường"
        )
    console.rule()

    state.all_pass     = all_pass
    state.final_report = (
        f"{'PASS' if all_pass else 'FAIL'} | "
        f"Missing: {len(all_missing)} | Mismatches: {len(all_mismatches)}"
    )
    return state
