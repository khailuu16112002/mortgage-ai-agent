"""
Borrower Agent — validate domain 'borrower' từ Driver's License PDF.

Fields cần verify (từ XML baseline):
  full_name, dob, current_address, current_city, current_state, current_zip,
  phone, email, marital_status, citizenship, gender
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message

console = Console()
client = OpenAI()

SYSTEM = """You are a mortgage document verification specialist.
Extract borrower identity info from driver's license PDFs.
Return ONLY valid JSON (no markdown, no explanation):
{
  "borrowers": [
    {
      "full_name": "",
      "dob": "YYYY-MM-DD",
      "address": "",
      "city": "",
      "state": "",
      "zip": "",
      "gender": "",
      "dl_number": "",
      "expiry": "YYYY-MM-DD"
    }
  ]
}"""


def borrower_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold blue]👤 BORROWER AGENT[/bold blue]")
    result = AgentResult("borrower")
    baseline = state.baseline
    dl_files = state.classified_files.get(DocType.DRIVER_LICENSE, [])

    if not dl_files:
        msg = "Driver's License — driverslicensebeckyandpatrick.pdf"
        result.missing_docs.append(msg)
        result.findings.append(ValidationFinding("Driver's License", "Required", "MISSING", False, True))
        console.print(f"[yellow]⚠ THIẾU: {msg}[/yellow]")
        result.status = "missing"
        state.borrower_result = result
        return state

    xml_facts = {k: v for k, v in state.flat_facts.items() if k.startswith("borrower.")}
    console.print(f"[dim]→ {len(xml_facts)} borrower facts từ JSON baseline[/dim]")

    console.print(f"[cyan]→ AI đọc {len(dl_files)} DL file(s)...[/cyan]")
    try:
        content = build_pdf_message(dl_files[:2],
            "Extract all borrower identity information from these driver's license documents.")
        resp = client.chat.completions.create(
            model="gpt-4o", max_tokens=1000,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": content}
            ]
        )
        raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
        pdf_borrowers = json.loads(raw).get("borrowers", [])
        console.print(f"[green]✓ Trích xuất {len(pdf_borrowers)} borrower(s) từ DL[/green]")
    except Exception as e:
        console.print(f"[red]✗ Lỗi đọc DL: {e}[/red]")
        result.mismatches.append(f"Không đọc được Driver's License: {e}")
        result.status = "mismatch"
        state.borrower_result = result
        return state

    for bx in baseline.borrowers:
        last = bx.last_name.lower()
        pdf_b = next(
            (b for b in pdf_borrowers if last in b.get("full_name", "").lower()),
            pdf_borrowers.pop(0) if pdf_borrowers else None
        )

        if pdf_b is None:
            result.findings.append(ValidationFinding(
                f"{bx.full_name} — not in DL", f"DOB: {bx.dob}", "Not found", False))
            result.mismatches.append(f"Không tìm thấy {bx.full_name} trong Driver's License")
            console.print(f"  [red]✗ {bx.full_name}: không tìm thấy[/red]")
            continue

        # DOB
        pdf_dob = pdf_b.get("dob", "")
        dob_ok = pdf_dob == bx.dob
        result.findings.append(ValidationFinding(f"{bx.full_name} — DOB", bx.dob, pdf_dob, dob_ok))
        if not dob_ok:
            result.mismatches.append(f"DOB sai ({bx.full_name}): XML={bx.dob} | DL={pdf_dob}")
        console.print(f"  {'[green]✓' if dob_ok else '[red]✗'} {bx.full_name} DOB: {pdf_dob}[/]")

        # Address
        pdf_addr = pdf_b.get("address", "").lower()
        xml_words = bx.current_address.lower().split()[:3]
        addr_ok = all(w in pdf_addr for w in xml_words) if pdf_addr and xml_words else False
        result.findings.append(ValidationFinding(
            f"{bx.full_name} — Address",
            f"{bx.current_address}, {bx.current_city}, {bx.current_state} {bx.current_zip}",
            f"{pdf_b.get('address','')}, {pdf_b.get('city','')}, {pdf_b.get('state','')} {pdf_b.get('zip','')}",
            addr_ok
        ))
        if not addr_ok:
            result.mismatches.append(f"Address sai ({bx.full_name}): XML={bx.current_address}")
        console.print(f"  {'[green]✓' if addr_ok else '[yellow]?'} {bx.full_name} Addr: {pdf_b.get('address','')}[/]")

        # Gender
        pdf_gender = pdf_b.get("gender", "").lower()
        xml_gender = bx.gender.lower()
        gender_ok = pdf_gender == xml_gender if pdf_gender and xml_gender else True
        result.findings.append(ValidationFinding(f"{bx.full_name} — Gender", bx.gender, pdf_b.get("gender","N/A"), gender_ok))
        console.print(f"  {'[green]✓' if gender_ok else '[red]✗'} {bx.full_name} Gender: {pdf_b.get('gender','')}[/]")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Borrower Agent")
    state.borrower_result = result
    return state
