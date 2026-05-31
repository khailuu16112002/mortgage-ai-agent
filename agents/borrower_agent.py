"""
Borrower Agent — validate domain 'borrower' từ Driver's License PDF.

Fields cần verify (từ XML baseline):
  full_name, dob, current_address, current_city, current_state, current_zip,
  phone, email, marital_status, citizenship, gender

FIX v2:
- Tự động detect DL là text hay ảnh scan (read_pdf_smart)
- Nếu ảnh → gửi base64 PNG lên GPT-4o Vision (image_url blocks)
- Nếu text → gửi text như cũ
- clean_json_response() tránh JSON parse lỗi
- Raise riêng từng field: DOB, Address, City, State, ZIP, Gender, DL#, Expiry
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding, make_finding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message, clean_json_response, read_pdf_smart

console = Console()
client = OpenAI()

SYSTEM = """You are a mortgage document verification specialist.
Extract borrower identity information from driver's license documents (text or image).
Look carefully at ALL visible fields on the license.
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
      "expiry": "YYYY-MM-DD",
      "issue_date": "YYYY-MM-DD"
    }
  ]
}
Notes:
- dob: Date of Birth field (DOB or BIRTH DATE), format YYYY-MM-DD
- expiry: Expiration Date field, format YYYY-MM-DD
- gender: use "M" or "F"
- If a field is not visible, use empty string ""
- One borrower object per license found in the document"""


def _norm_gender(g: str) -> str:
    g = g.strip().upper()
    if g in ("M", "MALE", "MASCULINO"):
        return "M"
    if g in ("F", "FEMALE", "FEMENINO"):
        return "F"
    return g


def borrower_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold blue]👤 BORROWER AGENT[/bold blue]")
    result = AgentResult("borrower")
    baseline = state.baseline
    dl_files = state.classified_files.get(DocType.DRIVER_LICENSE, [])

    if not dl_files:
        msg = "Driver's License — driverslicensebeckyandpatrick.pdf"
        result.missing_docs.append(msg)
        result.findings.append(make_finding(
            "Driver's License", "Required", "", None, force_missing=True))
        result.files_to_reupload.append({
            "file_type": "Driver's License",
            "reason": "Không tìm thấy file Driver's License nào được upload",
            "suggested_name": "driverslicensebeckyandpatrick.pdf",
        })
        console.print(f"[yellow]⚠ THIẾU: {msg}[/yellow]")
        result.status = "missing"
        state.borrower_result = result
        return state

    xml_facts = {k: v for k, v in state.flat_facts.items() if k.startswith("borrower.")}
    console.print(f"[dim]→ {len(xml_facts)} borrower facts từ JSON baseline[/dim]")

    # ── Detect PDF mode (text vs image) ───────────────────────────────────────
    unique_dl = list(dict.fromkeys(dl_files))[:2]   # de-dup, max 2 files
    modes = []
    for f in unique_dl:
        info = read_pdf_smart(f)
        modes.append(info["mode"])
    
    vision_needed = any(m == "images" for m in modes)
    console.print(
        f"[cyan]→ AI đọc {len(unique_dl)} DL file(s) "
        f"[{'👁 Vision (ảnh scan)' if vision_needed else '📄 Text'}]...[/cyan]"
    )

    try:
        content = build_pdf_message(
            unique_dl,
            "Extract all borrower identity information visible on the driver's license(s). "
            "There may be 1 or 2 licenses in the document — extract each as a separate borrower object."
        )
        resp = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1500,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": content}
            ]
        )
        raw = clean_json_response(resp.choices[0].message.content)
        parsed = json.loads(raw)
        pdf_borrowers = parsed.get("borrowers", [])

        if not pdf_borrowers:
            console.print("[red]✗ Không trích xuất được borrower nào từ DL[/red]")
            for bx in baseline.borrowers:
                for fn, xv in [
                    ("DOB", bx.dob), ("Address", bx.current_address),
                    ("City", bx.current_city), ("State", bx.current_state),
                    ("ZIP", bx.current_zip), ("Gender", bx.gender),
                    ("DL Number", "Required"), ("DL Expiry", "Required"),
                ]:
                    result.findings.append(make_finding(
                        f"{bx.full_name} — {fn}", xv, "", None, force_missing=True))
            result.files_to_reupload.append({
                "file_type": "Driver's License",
                "reason": "AI không đọc được nội dung — file có thể bị mờ, scan chất lượng thấp, hoặc sai loại tài liệu",
                "suggested_name": "driverslicensebeckyandpatrick.pdf",
            })
            result.status = "missing"
            state.borrower_result = result
            return state

        console.print(f"[green]✓ Trích xuất {len(pdf_borrowers)} borrower(s) từ DL[/green]")

    except Exception as e:
        console.print(f"[red]✗ Lỗi đọc DL: {e}[/red]")
        result.mismatches.append(f"Không đọc được Driver's License: {e}")
        result.status = "mismatch"
        state.borrower_result = result
        return state

    # ── Validate từng borrower ────────────────────────────────────────────────
    remaining = list(pdf_borrowers)

    for bx in baseline.borrowers:
        last = bx.last_name.lower()
        first = bx.first_name.lower() if hasattr(bx, "first_name") else ""

        # Match: ưu tiên last name, fallback first name, fallback lấy đầu tiên còn lại
        pdf_b = next(
            (b for b in remaining if last in b.get("full_name", "").lower()),
            None
        )
        if pdf_b is None and first:
            pdf_b = next(
                (b for b in remaining if first in b.get("full_name", "").lower()),
                None
            )
        if pdf_b is None and remaining:
            pdf_b = remaining[0]

        if pdf_b and pdf_b in remaining:
            remaining.remove(pdf_b)

        if pdf_b is None:
            for fn, xv in [
                ("DOB", bx.dob), ("Address", bx.current_address),
                ("City", bx.current_city), ("State", bx.current_state),
                ("ZIP", bx.current_zip), ("Gender", bx.gender),
                ("DL Number", "Required"), ("DL Expiry", "Required"),
            ]:
                result.findings.append(make_finding(
                    f"{bx.full_name} — {fn}", xv, "", None, force_missing=True))
            result.files_to_reupload.append({
                "file_type": "Driver's License",
                "reason": f"Không tìm thấy thông tin của '{bx.full_name}' trong Driver's License đã upload",
                "suggested_name": "driverslicensebeckyandpatrick.pdf",
            })
            result.mismatches.append(
                f"Không tìm thấy {bx.full_name} trong Driver's License")
            console.print(f"  [yellow]⚠ {bx.full_name}: không tìm thấy trong DL → MISSING[/yellow]")
            continue

        console.print(f"  [dim]→ Matched: {pdf_b.get('full_name','?')}[/dim]")

        # ── DOB ──────────────────────────────────────────────────────────────
        pdf_dob = (pdf_b.get("dob") or "").strip()
        dob_ok = pdf_dob == bx.dob if pdf_dob else None
        result.findings.append(make_finding(
            f"{bx.full_name} — DOB", bx.dob, pdf_dob, dob_ok))
        if pdf_dob and dob_ok is False:
            result.mismatches.append(
                f"DOB sai ({bx.full_name}): XML={bx.dob} | DL={pdf_dob}")
        console.print(f"  {'[green]✓' if dob_ok else ('[yellow]⚠' if not pdf_dob else '[red]✗')} {bx.full_name} DOB: {pdf_dob or 'MISSING'}[/]")

        # ── Address ───────────────────────────────────────────────────────────
        pdf_addr = (pdf_b.get("address") or "").strip()
        xml_words = bx.current_address.lower().split()[:3]
        addr_ok = all(w in pdf_addr.lower() for w in xml_words) if pdf_addr and xml_words else None
        result.findings.append(make_finding(
            f"{bx.full_name} — Address", bx.current_address, pdf_addr, addr_ok))
        if pdf_addr and addr_ok is False:
            result.mismatches.append(
                f"Address sai ({bx.full_name}): XML={bx.current_address} | DL={pdf_addr}")
        console.print(f"  {'[green]✓' if addr_ok else ('[yellow]⚠' if not pdf_addr else '[red]✗')} {bx.full_name} Address: {pdf_addr or 'MISSING'}[/]")

        # ── City ──────────────────────────────────────────────────────────────
        pdf_city = (pdf_b.get("city") or "").strip()
        city_ok = bx.current_city.lower() in pdf_city.lower() if pdf_city else None
        result.findings.append(make_finding(
            f"{bx.full_name} — City", bx.current_city, pdf_city, city_ok))
        if pdf_city and city_ok is False:
            result.mismatches.append(
                f"City sai ({bx.full_name}): XML={bx.current_city} | DL={pdf_city}")
        console.print(f"  {'[green]✓' if city_ok else ('[yellow]⚠' if not pdf_city else '[red]✗')} {bx.full_name} City: {pdf_city or 'MISSING'}[/]")

        # ── State ─────────────────────────────────────────────────────────────
        pdf_state = (pdf_b.get("state") or "").strip().upper()
        xml_state = bx.current_state.strip().upper()
        state_ok = pdf_state == xml_state if pdf_state else None
        result.findings.append(make_finding(
            f"{bx.full_name} — State", xml_state, pdf_state, state_ok))
        if pdf_state and state_ok is False:
            result.mismatches.append(
                f"State sai ({bx.full_name}): XML={xml_state} | DL={pdf_state}")

        # ── ZIP ───────────────────────────────────────────────────────────────
        pdf_zip = (pdf_b.get("zip") or "").strip()
        zip_ok = pdf_zip[:5] == bx.current_zip[:5] if pdf_zip and bx.current_zip else None
        result.findings.append(make_finding(
            f"{bx.full_name} — ZIP", bx.current_zip, pdf_zip, zip_ok))
        if pdf_zip and zip_ok is False:
            result.mismatches.append(
                f"ZIP sai ({bx.full_name}): XML={bx.current_zip} | DL={pdf_zip}")

        # ── Gender ────────────────────────────────────────────────────────────
        pdf_gender = (pdf_b.get("gender") or "").strip()
        xml_gender = bx.gender.strip() if bx.gender else ""
        gender_ok = _norm_gender(pdf_gender) == _norm_gender(xml_gender) \
                    if pdf_gender and xml_gender else (True if not xml_gender else None)
        result.findings.append(make_finding(
            f"{bx.full_name} — Gender", bx.gender or "N/A", pdf_gender, gender_ok))
        if pdf_gender and gender_ok is False:
            result.mismatches.append(
                f"Gender sai ({bx.full_name}): XML={bx.gender} | DL={pdf_gender}")
        console.print(f"  {'[green]✓' if gender_ok else ('[yellow]⚠' if not pdf_gender else '[red]✗')} {bx.full_name} Gender: {pdf_gender or 'MISSING'}[/]")

        # ── DL Number ─────────────────────────────────────────────────────────
        dl_num = (pdf_b.get("dl_number") or "").strip()
        result.findings.append(make_finding(
            f"{bx.full_name} — DL Number", "Required", dl_num, bool(dl_num) or None))
        if not dl_num:
            result.files_to_reupload.append({
                "file_type": "Driver's License",
                "reason": f"Không đọc được DL Number của '{bx.full_name}' — có thể file bị mờ hoặc sai loại",
                "suggested_name": "driverslicensebeckyandpatrick.pdf",
            })
        console.print(f"  {'[green]✓' if dl_num else '[yellow]⚠'} {bx.full_name} DL#: {dl_num or 'MISSING'}[/]")

        # ── DL Expiry ─────────────────────────────────────────────────────────
        dl_exp = (pdf_b.get("expiry") or "").strip()
        result.findings.append(make_finding(
            f"{bx.full_name} — DL Expiry", "Required", dl_exp, bool(dl_exp) or None))
        if not dl_exp:
            result.files_to_reupload.append({
                "file_type": "Driver's License",
                "reason": f"Không đọc được ngày hết hạn DL của '{bx.full_name}'",
                "suggested_name": "driverslicensebeckyandpatrick.pdf",
            })
        console.print(f"  {'[green]✓' if dl_exp else '[yellow]⚠'} {bx.full_name} Expiry: {dl_exp or 'MISSING'}[/]")

        # ── Issue Date (bonus field) ───────────────────────────────────────────
        issue = (pdf_b.get("issue_date") or "").strip()
        if issue:
            result.findings.append(make_finding(
                f"{bx.full_name} — DL Issue Date",
                "Optional", issue, True))

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(
        f"\n[{'green' if result.status=='pass' else 'red'}]"
        f"{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — Borrower Agent"
    )
    state.borrower_result = result
    return state
