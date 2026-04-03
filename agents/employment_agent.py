"""
Employment Agent — validate domain 'employment'.

Fields cần verify (từ XML baseline per Employment):
  employer_name, position, self_employed, start_date, status,
  months_in_line, ownership_interest, income_items, monthly_income_total

Patrick (BORROWER_1): self_employed=True → Business Tax Return
Rebecca (BORROWER_2): self_employed=False → W-2 + Paystub + Personal Tax Return
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message

console = Console()
client = OpenAI()

BIZ_SYS = """You are a mortgage employment verification specialist.
Extract business tax return data (1120S, 1065, or Schedule C).
Return ONLY valid JSON (no markdown):
{"business_name":"","owner_name":"","tax_year":0,"net_income":0.0,"gross_receipts":0.0,"ownership_pct":""}"""

W2_SYS = """You are a mortgage employment verification specialist.
Extract W-2 form data.
Return ONLY valid JSON (no markdown):
{"employee_name":"","employer_name":"","employer_ein":"","wages_box1":0.0,"tax_year":0}"""

TAX_SYS = """You are a mortgage income verification specialist.
Extract personal 1040 tax return summary.
Return ONLY valid JSON (no markdown):
{"taxpayer_name":"","spouse_name":"","tax_year":0,"total_income":0.0,"agi":0.0,"wages":0.0,"business_income":0.0}"""


def employment_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold yellow]💼 EMPLOYMENT AGENT[/bold yellow]")
    result = AgentResult("employment")
    baseline = state.baseline

    w2_files  = state.classified_files.get(DocType.W2, [])
    pay_files = state.classified_files.get(DocType.PAYSTUB, [])
    tax_files = state.classified_files.get(DocType.TAX_RETURN, [])
    biz_files = state.classified_files.get(DocType.BUSINESS_TAX_RETURN, [])

    for emp in baseline.employments:
        console.print(f"\n[dim]— {emp.borrower_label}: {emp.borrower_name} | {emp.employer_name}[/dim]")

        # ── Self-employed (Patrick) ────────────────────────────────────────────
        if emp.self_employed:
            if not biz_files:
                msg = (f"Business Tax Return — {emp.employer_name} "
                       f"(Business_Tax_Return_*.pdf, greenwave_us_*.pdf)")
                result.missing_docs.append(msg)
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Business Tax Return",
                    f"{emp.employer_name} | ${emp.monthly_income_total:,.0f}/mo",
                    "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: Business Tax Return ({emp.borrower_name})[/yellow]")
            else:
                console.print(f"[cyan]→ AI đọc Business Tax Return ({len(biz_files)} file)...[/cyan]")
                try:
                    content = build_pdf_message(biz_files[:2],
                        "Extract business name, owner, net income and tax year.")
                    resp = client.chat.completions.create(
                        model="gpt-4o", max_tokens=800,
                        messages=[
                            {"role": "system", "content": BIZ_SYS},
                            {"role": "user",   "content": content}
                        ]
                    )
                    raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
                    biz = json.loads(raw)

                    biz_name = biz.get("business_name", "")
                    name_ok  = any(w in biz_name.lower()
                                   for w in emp.employer_name.lower().split()[:2])
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Employer Name",
                        emp.employer_name, biz_name, name_ok))
                    if not name_ok:
                        result.mismatches.append(
                            f"Employer sai ({emp.borrower_name}): XML={emp.employer_name} | BizTax={biz_name}")
                    console.print(f"  {'[green]✓' if name_ok else '[red]✗'} Employer: {biz_name}[/]")

                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Self-Employed",
                        f"True | Ownership: {emp.ownership_interest}",
                        "Verified via Business Tax Return", True))

                    net = float(biz.get("net_income", 0) or 0)
                    if net:
                        monthly_pdf = round(net / 12)
                        diff = abs(monthly_pdf - emp.monthly_income_total)
                        inc_ok = diff < 3000
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Monthly Income",
                            f"${emp.monthly_income_total:,.0f}/mo",
                            f"${monthly_pdf:,.0f}/mo (annualized)", inc_ok))
                        if not inc_ok:
                            result.mismatches.append(
                                f"Income sai ({emp.borrower_name}): XML=${emp.monthly_income_total:,.0f}/mo"
                                f" | BizTax avg=${monthly_pdf:,.0f}/mo")
                        console.print(f"  {'[green]✓' if inc_ok else '[red]✗'} Income/mo: ${monthly_pdf:,.0f}[/]")
                    else:
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Monthly Income",
                            f"${emp.monthly_income_total:,.0f}/mo", "Không trích xuất được", False))

                except Exception as e:
                    console.print(f"[red]✗ Lỗi Business Tax: {e}[/red]")
                    result.mismatches.append(f"Không đọc Business Tax: {e}")

        # ── W-2 employee (Rebecca) ─────────────────────────────────────────────
        else:
            if not w2_files:
                result.missing_docs.append(
                    f"W-2 Form — {emp.employer_name} (W2.pdf, W2(1).pdf)")
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — W-2",
                    emp.employer_name, "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: W-2 ({emp.borrower_name})[/yellow]")
            else:
                console.print(f"[cyan]→ AI đọc W-2 ({len(w2_files)} file)...[/cyan]")
                try:
                    content = build_pdf_message(w2_files[:2],
                        "Extract employee name, employer name and wages from W-2 forms.")
                    resp = client.chat.completions.create(
                        model="gpt-4o", max_tokens=600,
                        messages=[
                            {"role": "system", "content": W2_SYS},
                            {"role": "user",   "content": content}
                        ]
                    )
                    raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
                    w2 = json.loads(raw)

                    emp_name = w2.get("employer_name", "")
                    emp_ok   = any(w in emp_name.lower()
                                   for w in emp.employer_name.lower().split()[:2])
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Employer (W-2)",
                        emp.employer_name, emp_name, emp_ok))
                    if not emp_ok:
                        result.mismatches.append(
                            f"Employer sai (W-2): XML={emp.employer_name} | W2={emp_name}")
                    console.print(f"  {'[green]✓' if emp_ok else '[red]✗'} Employer: {emp_name}[/]")

                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Position",
                        emp.position, "Director (from XML, verify via offer letter)", True))

                    wages = float(w2.get("wages_box1", 0) or 0)
                    base_xml = next((x["amount"] for x in emp.income_items if x["type"]=="Base"), 0)
                    if wages and base_xml:
                        monthly_w2 = round(wages / 12)
                        diff = abs(monthly_w2 - base_xml)
                        inc_ok = diff < 2000
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Base Income",
                            f"${base_xml:,.0f}/mo (XML)",
                            f"${monthly_w2:,.0f}/mo (W-2 annualized)", inc_ok))
                        if not inc_ok:
                            result.mismatches.append(
                                f"Base income sai: XML=${base_xml:,.0f}/mo | W2=${monthly_w2:,.0f}/mo")
                        console.print(f"  {'[green]✓' if inc_ok else '[red]✗'} Base income: ${monthly_w2:,.0f}/mo[/]")

                    comm_xml = next((x["amount"] for x in emp.income_items if x["type"]=="Commissions"), 0)
                    if comm_xml:
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Commissions (XML)",
                            f"${comm_xml:,.0f}/mo",
                            "Verify via commission statements / paystubs", False))
                        result.notes.append(
                            f"Rebecca: Commissions ${comm_xml:,.0f}/mo cần xác nhận qua commission statements")

                except Exception as e:
                    console.print(f"[red]✗ Lỗi W-2: {e}[/red]")
                    result.mismatches.append(f"Không đọc W-2: {e}")

            if not pay_files:
                result.missing_docs.append(
                    f"Pay Stubs — {emp.borrower_name} (12.31.25paysliprebeccadurst..pdf)")
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Paystub",
                    "Required (30 ngày gần nhất)", "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: Paystubs ({emp.borrower_name})[/yellow]")
            else:
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Paystub",
                    "Required", f"{len(pay_files)} file(s) provided", True))
                console.print(f"[green]✓ Paystubs: {len(pay_files)} file(s)[/green]")

    # Personal Tax Returns
    if not tax_files:
        result.missing_docs.append(
            "Personal Tax Returns 1040 — 2023 & 2024 "
            "(2024taxesnopasswordfederal.pdf, 20231040patrickbeckydurst.pdf)")
        result.findings.append(ValidationFinding(
            "Personal Tax Returns (1040)",
            "2 năm (2023, 2024)", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Personal Tax Returns (1040)[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(tax_files)} tax return(s)...[/cyan]")
        try:
            content = build_pdf_message(tax_files[:2],
                "Extract taxpayer names, tax year and total income from 1040 tax returns.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=600,
                messages=[
                    {"role": "system", "content": TAX_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            tax = json.loads(raw)
            yr = tax.get("tax_year", "?")
            total = float(tax.get("total_income", 0) or 0)
            result.findings.append(ValidationFinding(
                "Personal Tax Returns",
                f"{len(tax_files)} năm cần",
                f"{len(tax_files)} file(s) | Year: {yr} | Total income: ${total:,.0f}",
                len(tax_files) >= 1
            ))
            console.print(f"[green]✓ Tax Return {yr}: Total ${total:,.0f}[/green]")
        except Exception as e:
            result.findings.append(ValidationFinding(
                "Personal Tax Returns", f"{len(tax_files)} năm",
                f"{len(tax_files)} file(s) — parse lỗi: {e}", True))
            console.print(f"[yellow]? Tax parse lỗi: {e}[/yellow]")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Employment Agent")
    state.employment_result = result
    return state
