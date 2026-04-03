"""
REO Agent — validate domain 'real_estate_owned'.

Fields cần verify (từ XML baseline per RealEstateOwned):
  address, city, state, zip_code, current_usage, usage_type,
  estimated_value, disposition, maintenance_expense, rental_income_gross
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message

console = Console()
client = OpenAI()

REO_SYS = """You are a mortgage REO (Real Estate Owned) verification specialist.
Extract property information from REO or appraisal documents.
Return ONLY valid JSON (no markdown):
{"properties":[{"address":"","city":"","state":"","zip":"","estimated_value":0.0,"usage_type":"","rental_income_monthly":0.0}]}"""

INS_SYS = """You are a mortgage insurance verification specialist.
Extract property insurance info.
Return ONLY valid JSON (no markdown):
{"policies":[{"property_address":"","insurer":"","coverage_amount":0.0,"annual_premium":0.0,"policy_number":"","expiry_date":""}]}"""

LEASE_SYS = """You are a mortgage income verification specialist.
Extract lease agreement details.
Return ONLY valid JSON (no markdown):
{"leases":[{"property_address":"","tenant_name":"","monthly_rent":0.0,"lease_start":"","lease_end":""}]}"""


def reo_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold red]🏠 REAL ESTATE OWNED AGENT[/bold red]")
    result = AgentResult("real_estate_owned")
    baseline = state.baseline

    reo_files   = state.classified_files.get(DocType.REO_DOC, [])
    ins_files   = state.classified_files.get(DocType.INSURANCE, [])
    lease_files = state.classified_files.get(DocType.LEASE, [])

    xml_props = baseline.real_estate_owned
    console.print(f"[dim]XML properties: {len(xml_props)} | REO: {len(reo_files)} | Ins: {len(ins_files)} | Lease: {len(lease_files)}[/dim]")

    for r in xml_props:
        console.print(f"  [dim]→ {r.address}, {r.city}, {r.state} — ${r.estimated_value:,.0f} "
                      f"({r.current_usage}) rental=${r.rental_income_gross:,.0f}/mo[/dim]")

    # ── Insurance ──────────────────────────────────────────────────────────────
    if not ins_files:
        result.missing_docs.append(
            "Insurance Documents — *insurance*.pdf, clarksoninsurnace.pdf, "
            "washingtoninsurance.pdf, 463swashingtoninsurance.pdf")
        for r in xml_props:
            result.findings.append(ValidationFinding(
                f"Insurance: {r.address[:30]}",
                "Required", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Insurance Documents[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(ins_files)} insurance doc(s)...[/cyan]")
        try:
            content = build_pdf_message(ins_files[:3],
                "Extract all property addresses and insurance coverage amounts.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=800,
                messages=[
                    {"role": "system", "content": INS_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            policies = json.loads(raw).get("policies", [])
            console.print(f"[green]✓ {len(policies)} insurance policy/ies[/green]")
            for pol in policies:
                addr = pol.get("property_address","")
                cov  = float(pol.get("coverage_amount",0) or 0)
                result.findings.append(ValidationFinding(
                    f"Insurance: {addr[:35] or 'Property'}",
                    "Required",
                    f"{pol.get('insurer','?')} | ${cov:,.0f} coverage", True))
                console.print(f"  [green]✓ {addr[:40]}: ${cov:,.0f} ({pol.get('insurer','?')})[/green]")
        except Exception as e:
            console.print(f"[red]✗ Lỗi insurance: {e}[/red]")
            result.mismatches.append(f"Không đọc insurance: {e}")

    # ── REO Documentation ──────────────────────────────────────────────────────
    if not reo_files:
        result.missing_docs.append(
            "REO Documentation — 'REO Documentation.pdf', 'REO Documentation_ 1.pdf'")
        for r in xml_props:
            result.findings.append(ValidationFinding(
                f"REO Doc: {r.address[:30]}",
                f"${r.estimated_value:,.0f} | {r.current_usage}",
                "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: REO Documentation[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(reo_files)} REO doc(s)...[/cyan]")
        try:
            content = build_pdf_message(reo_files[:2],
                "Extract owned property addresses, estimated values, usage types and rental income.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=900,
                messages=[
                    {"role": "system", "content": REO_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            pdf_props = json.loads(raw).get("properties", [])
            console.print(f"[green]✓ {len(pdf_props)} property/ies trong REO docs[/green]")

            for bx in xml_props:
                street_num = bx.address.split()[0]
                found = next((
                    p for p in pdf_props
                    if street_num in p.get("address","")
                    or bx.city.lower() in p.get("city","").lower()
                ), None)

                if found:
                    val = float(found.get("estimated_value", 0) or 0)
                    ok  = abs(val - bx.estimated_value) < max(bx.estimated_value * 0.10, 5000) if val else False
                    result.findings.append(ValidationFinding(
                        f"{bx.address[:30]}, {bx.state}",
                        f"${bx.estimated_value:,.0f} | {bx.current_usage}",
                        f"${val:,.0f}", ok))
                    if not ok and val:
                        result.mismatches.append(
                            f"Property value sai: {bx.address} — XML=${bx.estimated_value:,.0f} | REO=${val:,.0f}")
                    console.print(f"  {'[green]✓' if ok else '[yellow]?'} {bx.address[:30]}: ${val:,.0f}[/]")

                    rental_pdf = float(found.get("rental_income_monthly", 0) or 0)
                    if rental_pdf != bx.rental_income_gross:
                        result.findings.append(ValidationFinding(
                            f"Rental Income: {bx.address[:25]}",
                            f"${bx.rental_income_gross:,.0f}/mo (XML)",
                            f"${rental_pdf:,.0f}/mo (REO doc)", False))
                        result.mismatches.append(
                            f"Rental income sai: {bx.address} — XML=${bx.rental_income_gross:,.0f} | REO=${rental_pdf:,.0f}")
                    else:
                        result.findings.append(ValidationFinding(
                            f"Rental Income: {bx.address[:25]}",
                            f"${bx.rental_income_gross:,.0f}/mo", f"${rental_pdf:,.0f}/mo", True))
                else:
                    result.findings.append(ValidationFinding(
                        f"{bx.address[:30]}",
                        f"${bx.estimated_value:,.0f}", "Không tìm thấy trong REO docs", False))
                    console.print(f"  [yellow]? {bx.address[:40]}: không khớp[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ Lỗi REO: {e}[/red]")
            result.mismatches.append(f"Không đọc REO docs: {e}")

    # ── Lease Agreements ───────────────────────────────────────────────────────
    if lease_files:
        console.print(f"[cyan]→ AI đọc {len(lease_files)} lease agreement(s)...[/cyan]")
        try:
            content = build_pdf_message(lease_files[:2],
                "Extract property address, tenant name and monthly rent from lease agreements.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=600,
                messages=[
                    {"role": "system", "content": LEASE_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = resp.choices[0].message.content.strip().lstrip("```json").rstrip("```").strip()
            leases = json.loads(raw).get("leases", [])
            total_rent = sum(float(l.get("monthly_rent", 0) or 0) for l in leases)
            xml_total_rental = sum(p.rental_income_gross for p in xml_props)

            if total_rent > 0 and xml_total_rental == 0:
                tenants = ", ".join(l.get("tenant_name","?") for l in leases)
                result.mismatches.append(
                    f"Rental income mâu thuẫn: XML khai báo $0/mo nhưng có {len(leases)} lease "
                    f"(total ${total_rent:,.0f}/mo, tenants: {tenants}). Cần xác nhận lại.")
                result.findings.append(ValidationFinding(
                    "Rental Income — XML vs Lease",
                    "$0.00/mo (XML — tất cả properties)",
                    f"${total_rent:,.0f}/mo ({len(leases)} lease: {tenants})",
                    False))
                console.print(f"[red]✗ Mâu thuẫn rental: XML=$0 nhưng có lease ${total_rent:,.0f}/mo ({tenants})[/red]")
            else:
                for l in leases:
                    rent = float(l.get("monthly_rent",0) or 0)
                    result.findings.append(ValidationFinding(
                        f"Lease: {l.get('tenant_name','?')}",
                        "Lease document", f"${rent:,.0f}/mo", True))
                console.print(f"[green]✓ {len(leases)} lease(s) | Total: ${total_rent:,.0f}/mo[/green]")
        except Exception as e:
            console.print(f"[yellow]? Lease parse lỗi: {e}[/yellow]")
            result.findings.append(ValidationFinding(
                "Lease Agreements", "Present", f"{len(lease_files)} file(s)", True))
    else:
        result.notes.append("Không có lease agreements — phù hợp với rental income $0 trong XML")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — REO Agent")
    state.reo_result = result
    return state
