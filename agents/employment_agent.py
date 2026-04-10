"""
Employment Agent — validate domain 'employment'.

FIX:
- clean_json_response() — sửa lỗi "Extra data: line 2 column 1 (char 141)"
  Nguyên nhân: W2_SYS prompt cho return 1 object nhưng khi đọc 2 file W-2,
  AI trả về 2 JSON objects nối nhau. clean_json_response() lấy object đầu tiên.
- W2: đọc từng file riêng (1 file = 1 W-2) để match đúng borrower
- Raise riêng từng field: employer_name, wages, position, paystub_count, tax_year, income
- Raise commission field rõ ràng là UNVERIFIED
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message, clean_json_response

console = Console()
client = OpenAI()

BIZ_SYS = """You are a mortgage employment verification specialist.
Extract business tax return data (1120S, 1065, or Schedule C).
Return ONLY valid JSON (no markdown):
{"business_name":"","owner_name":"","tax_year":0,"net_income":0.0,"gross_receipts":0.0,"ownership_pct":""}"""

W2_SYS = """You are a mortgage employment verification specialist.
Extract W-2 form data from ONE W-2 document.
Return ONLY valid JSON (no markdown, single object):
{"employee_name":"","employer_name":"","employer_ein":"","wages_box1":0.0,"federal_tax_box2":0.0,"tax_year":0}"""

TAX_SYS = """You are a mortgage income verification specialist.
Extract personal 1040 tax return summary.
Return ONLY valid JSON (no markdown):
{"taxpayer_name":"","spouse_name":"","tax_year":0,"total_income":0.0,"agi":0.0,"wages":0.0,"business_income":0.0}"""


def _read_w2_files(client, w2_files: list) -> list:
    """
    Đọc từng file W-2 riêng để tránh Extra data error.
    Trả về list of w2 dicts.
    """
    results = []
    for fpath in w2_files:
        try:
            content = build_pdf_message([fpath],
                "Extract employee name, employer name, EIN and wages (Box 1) from this W-2 form.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=600,
                messages=[
                    {"role": "system", "content": W2_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = clean_json_response(resp.choices[0].message.content)
            w2 = json.loads(raw)
            if w2.get("employee_name") or w2.get("wages_box1"):
                results.append(w2)
        except Exception as e:
            console.print(f"  [yellow]⚠ W-2 parse lỗi ({fpath}): {e}[/yellow]")
    return results


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
            # Field: Self-employed flag
            result.findings.append(ValidationFinding(
                f"{emp.borrower_name} — Self-Employed",
                "True", "Confirmed (XML)", True
            ))
            # Field: Ownership Interest
            result.findings.append(ValidationFinding(
                f"{emp.borrower_name} — Ownership Interest",
                str(emp.ownership_interest), "Required (verify via Biz Tax Return)", None
            ))

            if not biz_files:
                msg = (f"Business Tax Return — {emp.employer_name} "
                       f"(Business_Tax_Return_*.pdf, greenwave_us_*.pdf)")
                result.missing_docs.append(msg)
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Business Tax Return",
                    f"{emp.employer_name}", "MISSING", False, True))
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Monthly Income (Self-Employed)",
                    f"${emp.monthly_income_total:,.0f}/mo", "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: Business Tax Return ({emp.borrower_name})[/yellow]")
            else:
                console.print(f"[cyan]→ AI đọc Business Tax Return ({len(biz_files)} file)...[/cyan]")
                try:
                    content = build_pdf_message(biz_files[:2],
                        "Extract business name, owner, net income, gross receipts and tax year.")
                    resp = client.chat.completions.create(
                        model="gpt-4o", max_tokens=800,
                        messages=[
                            {"role": "system", "content": BIZ_SYS},
                            {"role": "user",   "content": content}
                        ]
                    )
                    raw = clean_json_response(resp.choices[0].message.content)
                    biz = json.loads(raw)

                    # Field: Business Name
                    biz_name = biz.get("business_name", "")
                    name_ok  = any(w in biz_name.lower()
                                   for w in emp.employer_name.lower().split()[:2])
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Employer Name (Biz Tax)",
                        emp.employer_name, biz_name if biz_name else "Không đọc được", name_ok))
                    if not name_ok:
                        result.mismatches.append(
                            f"Employer sai ({emp.borrower_name}): XML={emp.employer_name} | BizTax={biz_name}")
                    console.print(f"  {'[green]✓' if name_ok else '[red]✗'} Employer: {biz_name}[/]")

                    # Field: Tax Year
                    biz_yr = biz.get("tax_year", 0)
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Biz Tax Year",
                        "2023 or 2024", str(biz_yr) if biz_yr else "Không đọc được",
                        biz_yr in (2023, 2024)
                    ))

                    # Field: Net Income / Monthly Income
                    net = float(biz.get("net_income", 0) or 0)
                    if net:
                        monthly_pdf = round(net / 12)
                        diff   = abs(monthly_pdf - emp.monthly_income_total)
                        inc_ok = diff < 3000
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Monthly Income (Biz Tax)",
                            f"${emp.monthly_income_total:,.0f}/mo (XML)",
                            f"${monthly_pdf:,.0f}/mo (annualized from ${net:,.0f} net)", inc_ok))
                        if not inc_ok:
                            result.mismatches.append(
                                f"Income sai ({emp.borrower_name}): XML=${emp.monthly_income_total:,.0f}/mo"
                                f" | BizTax avg=${monthly_pdf:,.0f}/mo")
                        console.print(f"  {'[green]✓' if inc_ok else '[red]✗'} Income/mo: ${monthly_pdf:,.0f}[/]")
                    else:
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Monthly Income (Biz Tax)",
                            f"${emp.monthly_income_total:,.0f}/mo", "Không trích xuất được net income", False))
                        result.mismatches.append(
                            f"Không đọc được net income từ Business Tax ({emp.borrower_name})")

                    # Field: Gross Receipts
                    gross = float(biz.get("gross_receipts", 0) or 0)
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Gross Receipts (Biz Tax)",
                        "Required", f"${gross:,.0f}" if gross else "Không đọc được", bool(gross)
                    ))

                except Exception as e:
                    console.print(f"[red]✗ Lỗi Business Tax: {e}[/red]")
                    result.mismatches.append(f"Không đọc Business Tax ({emp.borrower_name}): {e}")
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Business Tax Return",
                        emp.employer_name, f"Lỗi: {e}", False))

        # ── W-2 employee (Rebecca) ─────────────────────────────────────────────
        else:
            if not w2_files:
                result.missing_docs.append(
                    f"W-2 Form — {emp.employer_name} (W2.pdf, W2(1).pdf)")
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — W-2 Employer",
                    emp.employer_name, "MISSING", False, True))
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — W-2 Wages",
                    "Required", "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: W-2 ({emp.borrower_name})[/yellow]")
            else:
                console.print(f"[cyan]→ AI đọc W-2 ({len(w2_files)} file, từng file riêng)...[/cyan]")
                w2_list = _read_w2_files(client, w2_files)
                console.print(f"[green]✓ Đọc được {len(w2_list)} W-2[/green]")

                # Tìm W-2 của borrower này
                last = emp.borrower_name.split()[-1].lower()
                w2 = next(
                    (w for w in w2_list if last in (w.get("employee_name","") or "").lower()),
                    w2_list[0] if w2_list else None
                )

                if w2:
                    # Field: Employer Name
                    emp_name = w2.get("employer_name", "")
                    emp_ok   = any(w in emp_name.lower()
                                   for w in emp.employer_name.lower().split()[:2])
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Employer (W-2)",
                        emp.employer_name, emp_name if emp_name else "Không đọc được", emp_ok))
                    if not emp_ok:
                        result.mismatches.append(
                            f"Employer sai (W-2 {emp.borrower_name}): XML={emp.employer_name} | W2={emp_name}")
                    console.print(f"  {'[green]✓' if emp_ok else '[red]✗'} Employer: {emp_name}[/]")

                    # Field: Employee Name
                    emp_person = w2.get("employee_name", "")
                    name_ok = last in (emp_person or "").lower()
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — Employee Name (W-2)",
                        emp.borrower_name, emp_person if emp_person else "Không đọc được", name_ok))
                    if not name_ok:
                        result.mismatches.append(
                            f"Employee name không khớp (W-2): XML={emp.borrower_name} | W2={emp_person}")

                    # Field: EIN
                    ein = w2.get("employer_ein", "")
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — EIN (W-2)",
                        "Required", ein if ein else "Không đọc được", bool(ein)
                    ))

                    # Field: Tax Year
                    w2_yr = w2.get("tax_year", 0)
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — W-2 Tax Year",
                        "2023 or 2024", str(w2_yr) if w2_yr else "Không đọc được",
                        w2_yr in (2023, 2024)
                    ))

                    # Field: Wages vs XML Base Income
                    wages = float(w2.get("wages_box1", 0) or 0)
                    base_xml = next((x["amount"] for x in emp.income_items if x["type"] == "Base"), 0)
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — W-2 Wages (Box 1)",
                        f"${wages * 12 / 12:,.0f} annual" if wages else "Required",
                        f"${wages:,.0f} annual" if wages else "Không đọc được",
                        bool(wages)
                    ))
                    if wages and base_xml:
                        monthly_w2 = round(wages / 12)
                        diff       = abs(monthly_w2 - base_xml)
                        inc_ok     = diff < 2000
                        result.findings.append(ValidationFinding(
                            f"{emp.borrower_name} — Base Income vs W-2",
                            f"${base_xml:,.0f}/mo (XML)",
                            f"${monthly_w2:,.0f}/mo (W-2 ÷ 12)", inc_ok))
                        if not inc_ok:
                            result.mismatches.append(
                                f"Base income sai ({emp.borrower_name}): XML=${base_xml:,.0f}/mo | W2=${monthly_w2:,.0f}/mo")
                        console.print(f"  {'[green]✓' if inc_ok else '[red]✗'} Base income: ${monthly_w2:,.0f}/mo[/]")
                else:
                    result.findings.append(ValidationFinding(
                        f"{emp.borrower_name} — W-2",
                        emp.employer_name, "Không tìm thấy W-2 cho borrower này", False))
                    result.mismatches.append(
                        f"Không tìm thấy W-2 cho {emp.borrower_name} trong {len(w2_files)} files")

            # Field: Position
            result.findings.append(ValidationFinding(
                f"{emp.borrower_name} — Position",
                emp.position, emp.position + " (từ XML, verify via offer letter / HR)", True))

            # Field: Paystubs
            if not pay_files:
                result.missing_docs.append(
                    f"Pay Stubs — {emp.borrower_name} (12.31.25paysliprebeccadurst..pdf)")
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Paystub",
                    "Required (30 ngày gần nhất)", "MISSING", False, True))
                console.print(f"[yellow]⚠ THIẾU: Paystubs ({emp.borrower_name})[/yellow]")
            else:
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Paystub Count",
                    "Required", f"{len(pay_files)} file(s) provided", True))
                console.print(f"[green]✓ Paystubs: {len(pay_files)} file(s)[/green]")

            # Field: Commissions (flag as UNVERIFIED)
            comm_xml = next((x["amount"] for x in emp.income_items if x["type"] == "Commissions"), 0)
            if comm_xml:
                result.findings.append(ValidationFinding(
                    f"{emp.borrower_name} — Commissions",
                    f"${comm_xml:,.0f}/mo (XML)",
                    "UNVERIFIED — cần commission statements hoặc paystub detail", False))
                result.mismatches.append(
                    f"Commissions ${comm_xml:,.0f}/mo ({emp.borrower_name}) chưa được xác minh qua paystubs")
                result.notes.append(
                    f"{emp.borrower_name}: Commissions ${comm_xml:,.0f}/mo — cần commission statements")

    # ── Personal Tax Returns (1040) ────────────────────────────────────────────
    if not tax_files:
        result.missing_docs.append(
            "Personal Tax Returns 1040 — 2023 & 2024 "
            "(2024taxesnopasswordfederal.pdf, 20231040patrickbeckydurst.pdf)")
        result.findings.append(ValidationFinding(
            "Personal Tax Returns (1040)", "2 năm (2023, 2024)", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Personal Tax Returns (1040)[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(tax_files)} tax return(s)...[/cyan]")
        # Đọc từng file tax return riêng
        tax_results = []
        for fpath in tax_files[:4]:
            try:
                content = build_pdf_message([fpath],
                    "Extract taxpayer names, tax year, total income, AGI, wages, business income from this 1040.")
                resp = client.chat.completions.create(
                    model="gpt-4o", max_tokens=700,
                    messages=[
                        {"role": "system", "content": TAX_SYS},
                        {"role": "user",   "content": content}
                    ]
                )
                raw = clean_json_response(resp.choices[0].message.content)
                tax = json.loads(raw)
                if tax.get("tax_year") or tax.get("total_income"):
                    tax_results.append(tax)
            except Exception as e:
                console.print(f"  [yellow]? Tax parse lỗi ({fpath}): {e}[/yellow]")

        # Field: Tax Return Count
        result.findings.append(ValidationFinding(
            "Personal Tax Returns — File Count",
            "2 năm (2023, 2024)", f"{len(tax_files)} file(s) present", len(tax_files) >= 2
        ))

        years_found = []
        for tax in tax_results:
            yr    = tax.get("tax_year", "?")
            total = float(tax.get("total_income", 0) or 0)
            agi   = float(tax.get("agi", 0) or 0)
            wages = float(tax.get("wages", 0) or 0)
            biz   = float(tax.get("business_income", 0) or 0)

            result.findings.append(ValidationFinding(
                f"Tax Return {yr} — Total Income",
                "Required", f"${total:,.0f}", bool(total)
            ))
            result.findings.append(ValidationFinding(
                f"Tax Return {yr} — AGI",
                "Required", f"${agi:,.0f}" if agi else "Không đọc được", bool(agi)
            ))
            result.findings.append(ValidationFinding(
                f"Tax Return {yr} — Wages",
                "Required", f"${wages:,.0f}" if wages else "Không đọc được", bool(wages)
            ))
            result.findings.append(ValidationFinding(
                f"Tax Return {yr} — Business Income",
                "Required", f"${biz:,.0f}" if biz else "Không đọc được", bool(biz)
            ))
            years_found.append(str(yr))
            console.print(f"[green]✓ Tax Return {yr}: Total ${total:,.0f} | AGI ${agi:,.0f}[/green]")

        # Check both 2023 & 2024 present
        for yr_req in ("2023", "2024"):
            yr_ok = yr_req in years_found
            result.findings.append(ValidationFinding(
                f"Personal Tax Return {yr_req}",
                "Required", f"{'Present' if yr_ok else 'Không tìm thấy'}", yr_ok
            ))
            if not yr_ok:
                result.mismatches.append(f"Thiếu Tax Return năm {yr_req}")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Employment Agent")
    state.employment_result = result
    return state
