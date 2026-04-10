"""
Asset Agent — validate domain 'assets' từ bank statements + brokerage statements.

FIX:
- clean_json_response() để tránh JSON parse lỗi
- Đọc TẤT CẢ files (không giới hạn [:3]), gộp kết quả de-duplicate
- Raise riêng từng field: holder, account_id, asset_type, amount, statement_date
- Tolerance: bank ±5% hoặc ±$50; brokerage ±10% hoặc ±$500
- Account matching cải thiện: check last-4 + holder name
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message, clean_json_response

console = Console()
client = OpenAI()

BANK_SYS = """You are a mortgage asset verification specialist.
Extract ALL bank account details from bank statements.
Return ONLY valid JSON (no markdown):
{"accounts":[{"bank_name":"","account_number":"","account_type":"","ending_balance":0.0,"statement_date":"YYYY-MM-DD","holder_name":""}]}"""

BROK_SYS = """You are a mortgage asset verification specialist.
Extract ALL investment/brokerage account details from statements.
Return ONLY valid JSON (no markdown):
{"accounts":[{"institution":"","account_number":"","account_type":"","total_value":0.0,"statement_date":"YYYY-MM-DD","holder_name":""}]}"""


def _tail(s: str, n: int = 4) -> str:
    clean = s.replace("-", "").replace(" ", "")
    return clean[-n:] if len(clean) >= n else clean


def _batch_call(client, files: list, system: str, prompt: str, max_per_batch: int = 4) -> list:
    """
    Gửi files theo batch, merge kết quả accounts.
    Tránh context overflow khi có nhiều files.
    """
    all_accounts = []
    seen_accounts = set()

    for i in range(0, len(files), max_per_batch):
        batch = files[i: i + max_per_batch]
        try:
            content = build_pdf_message(batch, prompt)
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=1500,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": content}
                ]
            )
            raw = clean_json_response(resp.choices[0].message.content)
            parsed = json.loads(raw)
            accounts = parsed.get("accounts", [])
            for acct in accounts:
                # De-duplicate by account number tail
                acct_num = acct.get("account_number", "") or acct.get("institution", "")
                key = _tail(str(acct_num), 6)
                if key and key not in seen_accounts:
                    seen_accounts.add(key)
                    all_accounts.append(acct)
        except Exception as e:
            console.print(f"  [yellow]⚠ Batch {i//max_per_batch + 1} lỗi: {e}[/yellow]")

    return all_accounts


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
        for a in checking + trust:
            result.findings.append(ValidationFinding(
                f"{a.holder} [{a.asset_type}] ...{_tail(a.account_id)}",
                f"${a.amount:,.2f}", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Bank Statements[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(bank_files)} bank statement(s) theo batch...[/cyan]")
        pdf_accts = _batch_call(
            client, bank_files, BANK_SYS,
            "Extract ALL bank account numbers, ending balances, holder names and statement dates."
        )
        console.print(f"[green]✓ Tìm thấy {len(pdf_accts)} bank account(s)[/green]")

        for a in checking + trust:
            t4 = _tail(a.account_id)
            # Match: last-4 digits trong account_number
            found = next(
                (x for x in pdf_accts
                 if t4 in (x.get("account_number","") or "").replace("-","").replace(" ","")),
                None
            )

            if found:
                bal = float(found.get("ending_balance", 0) or 0)
                ok  = abs(bal - a.amount) <= max(a.amount * 0.05, 50)
                stmt_date = found.get("statement_date", "N/A")
                holder_pdf = found.get("holder_name", "")

                # Field: Balance
                result.findings.append(ValidationFinding(
                    f"{a.holder} [{a.asset_type}] ...{t4} — Balance",
                    f"${a.amount:,.2f}", f"${bal:,.2f}", ok
                ))
                # Field: Statement Date
                result.findings.append(ValidationFinding(
                    f"{a.holder} [{a.asset_type}] ...{t4} — Statement Date",
                    "Required", stmt_date, bool(stmt_date and stmt_date != "N/A")
                ))
                # Field: Holder Name
                holder_ok = a.holder.split()[-1].lower() in holder_pdf.lower() if holder_pdf else True
                result.findings.append(ValidationFinding(
                    f"{a.holder} [{a.asset_type}] ...{t4} — Holder",
                    a.holder, holder_pdf if holder_pdf else "N/A", holder_ok
                ))

                if not ok:
                    result.mismatches.append(
                        f"Balance sai — {a.holder} ...{t4}: XML=${a.amount:,.0f} | PDF=${bal:,.0f}")
                if not holder_ok:
                    result.mismatches.append(
                        f"Holder sai — {a.holder} ...{t4}: XML={a.holder} | PDF={holder_pdf}")
                console.print(f"  {'[green]✓' if ok else '[red]✗'} {a.holder} ...{t4}: ${bal:,.0f} ({stmt_date})[/]")
            else:
                result.findings.append(ValidationFinding(
                    f"{a.holder} [{a.asset_type}] ...{t4} — Balance",
                    f"${a.amount:,.2f}", "Không tìm thấy trong statements", False
                ))
                result.findings.append(ValidationFinding(
                    f"{a.holder} [{a.asset_type}] ...{t4} — Statement Date",
                    "Required", "Không tìm thấy", False
                ))
                result.mismatches.append(
                    f"Không tìm thấy account ...{t4} ({a.holder} {a.asset_type}) trong bank statements")
                console.print(f"  [yellow]? {a.holder} ...{t4}: không khớp[/yellow]")

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
        console.print(f"[cyan]→ AI đọc {len(brok_files)} brokerage statement(s) theo batch...[/cyan]")
        pdf_accts = _batch_call(
            client, brok_files, BROK_SYS,
            "Extract ALL investment account numbers, institution names, total portfolio values and statement dates."
        )
        console.print(f"[green]✓ Tìm thấy {len(pdf_accts)} investment account(s)[/green]")

        for a in stocks:
            t4 = _tail(a.account_id)
            # Match: last-4 trong account_number, hoặc account_id chứa segment khớp
            acct_id_clean = a.account_id.replace("-", "")
            found = next(
                (x for x in pdf_accts
                 if t4 in (x.get("account_number","") or "").replace("-","")
                 or any(seg in (x.get("account_number","") or "").replace("-","")
                        for seg in [acct_id_clean[i:i+4] for i in range(0, len(acct_id_clean)-3, 4)])),
                None
            )

            if found:
                val  = float(found.get("total_value", 0) or 0)
                ok   = abs(val - a.amount) <= max(a.amount * 0.10, 500)
                stmt_date = found.get("statement_date", "N/A")
                inst = found.get("institution", "N/A")

                # Field: Value
                result.findings.append(ValidationFinding(
                    f"{a.holder} [Stock] {a.account_id} — Value",
                    f"${a.amount:,.2f}", f"${val:,.2f}", ok
                ))
                # Field: Statement Date
                result.findings.append(ValidationFinding(
                    f"{a.holder} [Stock] {a.account_id} — Statement Date",
                    "Required", stmt_date, bool(stmt_date and stmt_date != "N/A")
                ))
                # Field: Institution
                result.findings.append(ValidationFinding(
                    f"{a.holder} [Stock] {a.account_id} — Institution",
                    "Required", inst, bool(inst and inst != "N/A")
                ))

                if not ok:
                    result.mismatches.append(
                        f"Balance sai — {a.holder} {a.account_id}: XML=${a.amount:,.0f} | PDF=${val:,.0f}")
                console.print(f"  {'[green]✓' if ok else '[red]✗'} {a.holder} {a.account_id}: ${val:,.0f} ({stmt_date})[/]")
            else:
                result.findings.append(ValidationFinding(
                    f"{a.holder} [Stock] {a.account_id} — Value",
                    f"${a.amount:,.2f}", "Không khớp / không tìm thấy", False
                ))
                result.findings.append(ValidationFinding(
                    f"{a.holder} [Stock] {a.account_id} — Statement Date",
                    "Required", "Không tìm thấy", False
                ))
                result.mismatches.append(
                    f"Không tìm thấy account {a.account_id} ({a.holder}) trong brokerage statements")
                console.print(f"  [red]✗ {a.holder} {a.account_id}: không khớp[/red]")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Asset Agent")
    state.asset_result = result
    return state
