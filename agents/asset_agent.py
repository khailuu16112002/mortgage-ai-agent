"""
Asset Agent — validate domain 'assets' từ bank statements + brokerage statements.

Fields cần verify (từ XML baseline per Asset):
  holder, account_id, asset_type, amount
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message

console = Console()
client = OpenAI()

BANK_SYS = """You are a mortgage asset verification specialist.
Extract bank account details from bank statements.
Return ONLY valid JSON (no markdown):
{"accounts":[{"bank_name":"","account_number":"","account_type":"","ending_balance":0.0,"statement_date":""}]}"""

BROK_SYS = """You are a mortgage asset verification specialist.
Extract investment/brokerage account details from statements.
Return ONLY valid JSON (no markdown):
{"accounts":[{"institution":"","account_number":"","account_type":"","total_value":0.0,"statement_date":""}]}"""


def _tail(s: str, n=4) -> str:
    clean = s.replace("-", "").replace(" ", "")
    return clean[-n:] if len(clean) >= n else clean


def asset_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold green]💰 ASSET AGENT[/bold green]")
    result = AgentResult("assets")
    baseline = state.baseline

    bank_files = state.classified_files.get(DocType.BANK_STATEMENT, [])
    brok_files = state.classified_files.get(DocType.BROKERAGE_STATEMENT, [])

    checking = [a for a in baseline.assets if a.asset_type == "CheckingAccount"]
    trust    = [a for a in baseline.assets if a.asset_type == "TrustAccount"]
    stocks   = [a for a in baseline.assets if a.asset_type == "Stock"]

    console.print(f"[dim]XML assets: {len(checking)} checking | {len(trust)} trust | {len(stocks)} stock[/dim]")
    console.print(f"[dim]PDFs: {len(bank_files)} bank | {len(brok_files)} brokerage[/dim]")

    # ── Bank statements ────────────────────────────────────────────────────────
    if not bank_files:
        result.missing_docs.append(
            "Bank Statements — bankstatement_*.pdf, _112625wellsfargo.pdf, _122325wellsfargo.pdf")
        for a in checking:
            result.findings.append(ValidationFinding(
                f"{a.holder} [{a.asset_type}] ...{_tail(a.account_id)}",
                f"${a.amount:,.2f}", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Bank Statements[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(bank_files)} bank statement(s)...[/cyan]")
        try:
            content = build_pdf_message(bank_files[:3],
                "Extract all bank account numbers and ending balances from these statements.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=1000,
                messages=[
                    {"role": "system", "content": BANK_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            pdf_accts = json.loads(raw).get("accounts", [])
            console.print(f"[green]✓ Tìm thấy {len(pdf_accts)} bank account(s)[/green]")

            for a in checking + trust:
                t4 = _tail(a.account_id)
                found = next(
                    (x for x in pdf_accts if t4 in x.get("account_number","").replace("-","").replace(" ","")),
                    None
                )
                if found:
                    bal = float(found.get("ending_balance", 0) or 0)
                    ok  = abs(bal - a.amount) <= max(a.amount * 0.05, 50)
                    result.findings.append(ValidationFinding(
                        f"{a.holder} [{a.asset_type}] ...{t4}",
                        f"${a.amount:,.2f}", f"${bal:,.2f}", ok
                    ))
                    if not ok:
                        result.mismatches.append(
                            f"Balance sai — {a.holder} ...{t4}: XML=${a.amount:,.0f} | PDF=${bal:,.0f}")
                    console.print(f"  {'[green]✓' if ok else '[red]✗'} {a.holder} ...{t4}: ${bal:,.0f}[/]")
                else:
                    result.findings.append(ValidationFinding(
                        f"{a.holder} [{a.asset_type}] ...{t4}",
                        f"${a.amount:,.2f}", "Không tìm thấy trong statements", False
                    ))
                    console.print(f"  [yellow]? {a.holder} ...{t4}: không khớp[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ Lỗi bank: {e}[/red]")
            result.mismatches.append(f"Không đọc được bank statements: {e}")

    # ── Brokerage statements ───────────────────────────────────────────────────
    if not brok_files:
        result.missing_docs.append(
            "Brokerage Statements — brokeragestatement_*.pdf (Charles Schwab, Fidelity)")
        for a in stocks:
            result.findings.append(ValidationFinding(
                f"{a.holder} [Stock] {a.account_id}",
                f"${a.amount:,.2f}", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Brokerage Statements[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(brok_files)} brokerage statement(s)...[/cyan]")
        try:
            content = build_pdf_message(brok_files[:5],
                "Extract all investment account numbers, institution names and total portfolio values.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=1200,
                messages=[
                    {"role": "system", "content": BROK_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            pdf_accts = json.loads(raw).get("accounts", [])
            console.print(f"[green]✓ Tìm thấy {len(pdf_accts)} investment account(s)[/green]")

            for a in stocks:
                t4 = _tail(a.account_id)
                found = next((
                    x for x in pdf_accts
                    if t4 in x.get("account_number","").replace("-","")
                    or a.holder.lower().split()[0] in x.get("institution","").lower()
                ), None)

                if found:
                    val = float(found.get("total_value", 0) or 0)
                    ok  = abs(val - a.amount) <= max(a.amount * 0.10, 500)
                    result.findings.append(ValidationFinding(
                        f"{a.holder} [Stock] {a.account_id}",
                        f"${a.amount:,.2f}", f"${val:,.2f}", ok
                    ))
                    if not ok:
                        result.mismatches.append(
                            f"Balance sai — {a.holder} {a.account_id}: XML=${a.amount:,.0f} | PDF=${val:,.0f}")
                    console.print(f"  {'[green]✓' if ok else '[red]✗'} {a.holder} {a.account_id}: ${val:,.0f}[/]")
                else:
                    result.findings.append(ValidationFinding(
                        f"{a.holder} [Stock] {a.account_id}",
                        f"${a.amount:,.2f}", "Không khớp", False
                    ))
        except Exception as e:
            console.print(f"[red]✗ Lỗi brokerage: {e}[/red]")
            result.mismatches.append(f"Không đọc được brokerage: {e}")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Asset Agent")
    state.asset_result = result
    return state
