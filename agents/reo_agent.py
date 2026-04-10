"""
REO Agent — validate domain 'real_estate_owned'.

FIX:
- clean_json_response() để tránh JSON parse lỗi
- Raise riêng từng field: address, estimated_value, usage_type, rental_income,
  insurance_coverage, insurance_carrier, insurance_policy#, lease_tenant, lease_rent, lease_dates
- Property value mismatch raise rõ ràng với delta
- Rental income: raise riêng từng property (không gộp chung)
- Insurance: match từng property address
"""
import json
from openai import OpenAI
from rich.console import Console
from agents.state import GraphState, AgentResult, ValidationFinding
from utils.file_classifier import DocType
from utils.pdf_reader import build_pdf_message, clean_json_response

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


def _addr_match(xml_addr: str, pdf_addr: str, xml_city: str = "") -> bool:
    """Loose address match: street number + first word of street name."""
    if not pdf_addr:
        return False
    parts = xml_addr.lower().split()
    if not parts:
        return False
    street_num = parts[0]
    street_word = parts[1] if len(parts) > 1 else ""
    pdf_l = pdf_addr.lower()
    return (street_num in pdf_l or xml_city.lower() in pdf_l) and \
           (not street_word or street_word in pdf_l)


def reo_agent_node(state: GraphState) -> GraphState:
    console.rule("[bold red]🏠 REAL ESTATE OWNED AGENT[/bold red]")
    result = AgentResult("real_estate_owned")
    baseline = state.baseline

    reo_files   = state.classified_files.get(DocType.REO_DOC, [])
    ins_files   = state.classified_files.get(DocType.INSURANCE, [])
    lease_files = state.classified_files.get(DocType.LEASE, [])

    xml_props = baseline.real_estate_owned
    console.print(f"[dim]XML properties: {len(xml_props)} | REO: {len(reo_files)} | "
                  f"Ins: {len(ins_files)} | Lease: {len(lease_files)}[/dim]")

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
                f"Insurance — Coverage: {r.address[:30]}",
                "Required", "MISSING", False, True))
            result.findings.append(ValidationFinding(
                f"Insurance — Carrier: {r.address[:30]}",
                "Required", "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: Insurance Documents[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(ins_files)} insurance doc(s)...[/cyan]")
        try:
            content = build_pdf_message(ins_files[:4],
                "Extract all property addresses, insurer names, coverage amounts, policy numbers and expiry dates.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=1000,
                messages=[
                    {"role": "system", "content": INS_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = clean_json_response(resp.choices[0].message.content)
            policies = json.loads(raw).get("policies", [])
            console.print(f"[green]✓ {len(policies)} insurance policy/ies[/green]")

            for bx in xml_props:
                # Match policy to property
                pol = next(
                    (p for p in policies if _addr_match(bx.address, p.get("property_address",""), bx.city)),
                    None
                )
                if pol:
                    cov       = float(pol.get("coverage_amount", 0) or 0)
                    carrier   = pol.get("insurer", "")
                    pol_num   = pol.get("policy_number", "")
                    expiry    = pol.get("expiry_date", "")
                    premium   = float(pol.get("annual_premium", 0) or 0)

                    # Field: Coverage Amount
                    cov_ok = cov > 0
                    result.findings.append(ValidationFinding(
                        f"Insurance — Coverage: {bx.address[:30]}",
                        "Required (>$0)", f"${cov:,.0f} ({carrier})", cov_ok))
                    if not cov_ok:
                        result.mismatches.append(
                            f"Insurance coverage $0 cho {bx.address} — cần xác nhận")

                    # Field: Carrier
                    result.findings.append(ValidationFinding(
                        f"Insurance — Carrier: {bx.address[:30]}",
                        "Required", carrier if carrier else "Không đọc được", bool(carrier)))

                    # Field: Policy Number
                    result.findings.append(ValidationFinding(
                        f"Insurance — Policy #: {bx.address[:30]}",
                        "Required", pol_num if pol_num else "Không đọc được", bool(pol_num)))

                    # Field: Expiry Date
                    result.findings.append(ValidationFinding(
                        f"Insurance — Expiry: {bx.address[:30]}",
                        "Required", expiry if expiry else "Không đọc được", bool(expiry)))

                    # Field: Annual Premium
                    result.findings.append(ValidationFinding(
                        f"Insurance — Annual Premium: {bx.address[:30]}",
                        "Required", f"${premium:,.0f}/yr" if premium else "Không đọc được", bool(premium)))

                    console.print(f"  [green]✓ {bx.address[:35]}: ${cov:,.0f} ({carrier})[/green]")
                else:
                    result.findings.append(ValidationFinding(
                        f"Insurance — Coverage: {bx.address[:30]}",
                        "Required", "Không tìm thấy policy phù hợp", False))
                    result.findings.append(ValidationFinding(
                        f"Insurance — Carrier: {bx.address[:30]}",
                        "Required", "Không tìm thấy", False))
                    result.mismatches.append(
                        f"Không tìm thấy insurance policy cho {bx.address}")
                    console.print(f"  [red]✗ Không tìm thấy policy cho {bx.address[:40]}[/red]")

        except Exception as e:
            console.print(f"[red]✗ Lỗi insurance: {e}[/red]")
            result.mismatches.append(f"Không đọc insurance: {e}")

    # ── REO Documentation ──────────────────────────────────────────────────────
    if not reo_files:
        result.missing_docs.append(
            "REO Documentation — 'REO Documentation.pdf', 'REO Documentation_ 1.pdf'")
        for r in xml_props:
            result.findings.append(ValidationFinding(
                f"REO — Estimated Value: {r.address[:30]}",
                f"${r.estimated_value:,.0f}", "MISSING", False, True))
            result.findings.append(ValidationFinding(
                f"REO — Usage Type: {r.address[:30]}",
                r.current_usage, "MISSING", False, True))
        console.print("[yellow]⚠ THIẾU: REO Documentation[/yellow]")
    else:
        console.print(f"[cyan]→ AI đọc {len(reo_files)} REO doc(s)...[/cyan]")
        try:
            content = build_pdf_message(reo_files[:2],
                "Extract owned property addresses, estimated values, usage types and monthly rental income.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=900,
                messages=[
                    {"role": "system", "content": REO_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = clean_json_response(resp.choices[0].message.content)
            pdf_props = json.loads(raw).get("properties", [])
            console.print(f"[green]✓ {len(pdf_props)} property/ies trong REO docs[/green]")

            for bx in xml_props:
                found = next(
                    (p for p in pdf_props
                     if _addr_match(bx.address, p.get("address",""), bx.city)),
                    None
                )

                if found:
                    val          = float(found.get("estimated_value", 0) or 0)
                    usage        = found.get("usage_type", "")
                    rental_pdf   = float(found.get("rental_income_monthly", 0) or 0)
                    val_ok       = abs(val - bx.estimated_value) < max(bx.estimated_value * 0.10, 5000) if val else False
                    usage_ok     = usage.lower() in bx.current_usage.lower() or bx.current_usage.lower() in usage.lower() if usage else False

                    # Field: Estimated Value
                    result.findings.append(ValidationFinding(
                        f"REO — Estimated Value: {bx.address[:30]}",
                        f"${bx.estimated_value:,.0f}", f"${val:,.0f}", val_ok))
                    if not val_ok and val:
                        delta = val - bx.estimated_value
                        result.mismatches.append(
                            f"Property value sai: {bx.address} — XML=${bx.estimated_value:,.0f} | "
                            f"REO=${val:,.0f} (delta ${delta:+,.0f})")
                    elif not val:
                        result.mismatches.append(
                            f"Không đọc được estimated value: {bx.address}")
                    console.print(f"  {'[green]✓' if val_ok else '[yellow]?'} {bx.address[:30]}: ${val:,.0f}[/]")

                    # Field: Usage Type
                    result.findings.append(ValidationFinding(
                        f"REO — Usage Type: {bx.address[:30]}",
                        bx.current_usage, usage if usage else "Không đọc được", usage_ok))
                    if not usage_ok and usage:
                        result.mismatches.append(
                            f"Usage type sai: {bx.address} — XML={bx.current_usage} | REO={usage}")

                    # Field: Rental Income (per property)
                    rental_ok = abs(rental_pdf - bx.rental_income_gross) < 100
                    result.findings.append(ValidationFinding(
                        f"REO — Rental Income: {bx.address[:30]}",
                        f"${bx.rental_income_gross:,.0f}/mo (XML)",
                        f"${rental_pdf:,.0f}/mo (REO doc)", rental_ok))
                    if not rental_ok:
                        result.mismatches.append(
                            f"Rental income sai: {bx.address} — XML=${bx.rental_income_gross:,.0f} | "
                            f"REO=${rental_pdf:,.0f}/mo")
                    console.print(f"  {'[green]✓' if rental_ok else '[red]✗'} {bx.address[:25]} rental: ${rental_pdf:,.0f}/mo[/]")
                else:
                    result.findings.append(ValidationFinding(
                        f"REO — Estimated Value: {bx.address[:30]}",
                        f"${bx.estimated_value:,.0f}", "Không tìm thấy trong REO docs", False))
                    result.findings.append(ValidationFinding(
                        f"REO — Usage Type: {bx.address[:30]}",
                        bx.current_usage, "Không tìm thấy", False))
                    result.findings.append(ValidationFinding(
                        f"REO — Rental Income: {bx.address[:30]}",
                        f"${bx.rental_income_gross:,.0f}/mo", "Không tìm thấy", False))
                    result.mismatches.append(
                        f"Không tìm thấy {bx.address} trong REO docs")
                    console.print(f"  [yellow]? {bx.address[:40]}: không khớp[/yellow]")

        except Exception as e:
            console.print(f"[red]✗ Lỗi REO: {e}[/red]")
            result.mismatches.append(f"Không đọc REO docs: {e}")

    # ── Lease Agreements ───────────────────────────────────────────────────────
    if lease_files:
        console.print(f"[cyan]→ AI đọc {len(lease_files)} lease agreement(s)...[/cyan]")
        try:
            content = build_pdf_message(lease_files[:4],
                "Extract property address, tenant name, monthly rent, lease start and end dates from each lease.")
            resp = client.chat.completions.create(
                model="gpt-4o", max_tokens=800,
                messages=[
                    {"role": "system", "content": LEASE_SYS},
                    {"role": "user",   "content": content}
                ]
            )
            raw = clean_json_response(resp.choices[0].message.content)
            leases = json.loads(raw).get("leases", [])
            xml_total_rental = sum(p.rental_income_gross for p in xml_props)

            # Raise per lease
            for lse in leases:
                rent     = float(lse.get("monthly_rent", 0) or 0)
                tenant   = lse.get("tenant_name", "?")
                l_addr   = lse.get("property_address", "?")
                l_start  = lse.get("lease_start", "")
                l_end    = lse.get("lease_end", "")

                # Field: Tenant
                result.findings.append(ValidationFinding(
                    f"Lease — Tenant: {l_addr[:30]}",
                    "Required", tenant, bool(tenant and tenant != "?")))
                # Field: Monthly Rent
                result.findings.append(ValidationFinding(
                    f"Lease — Rent: {l_addr[:30]}",
                    "Required", f"${rent:,.0f}/mo", bool(rent)))
                # Field: Lease Start
                result.findings.append(ValidationFinding(
                    f"Lease — Start: {l_addr[:30]}",
                    "Required", l_start if l_start else "Không đọc được", bool(l_start)))
                # Field: Lease End
                result.findings.append(ValidationFinding(
                    f"Lease — End: {l_addr[:30]}",
                    "Required", l_end if l_end else "Không đọc được", bool(l_end)))
                console.print(f"  [green]✓ {tenant}: ${rent:,.0f}/mo ({l_addr[:30]})[/green]")

            # Cross-check: tổng lease rent vs XML rental income
            total_rent = sum(float(l.get("monthly_rent", 0) or 0) for l in leases)
            if total_rent > 0 and xml_total_rental == 0:
                tenants = ", ".join(l.get("tenant_name", "?") for l in leases)
                result.findings.append(ValidationFinding(
                    "Rental Income — XML vs Lease (Cross-check)",
                    "$0.00/mo (XML tất cả properties)",
                    f"${total_rent:,.0f}/mo ({len(leases)} lease: {tenants})", False))
                result.mismatches.append(
                    f"Rental income mâu thuẫn: XML khai báo $0/mo nhưng có {len(leases)} lease "
                    f"(total ${total_rent:,.0f}/mo, tenants: {tenants}). Cần xác nhận lại.")
                console.print(
                    f"[red]✗ Mâu thuẫn rental: XML=$0 nhưng có lease ${total_rent:,.0f}/mo ({tenants})[/red]")
            elif leases:
                result.findings.append(ValidationFinding(
                    "Rental Income — XML vs Lease (Cross-check)",
                    f"${xml_total_rental:,.0f}/mo (XML)", f"${total_rent:,.0f}/mo (Leases)",
                    abs(total_rent - xml_total_rental) < 100))
                console.print(f"[green]✓ {len(leases)} lease(s) | Total: ${total_rent:,.0f}/mo[/green]")

        except Exception as e:
            console.print(f"[yellow]? Lease parse lỗi: {e}[/yellow]")
            result.findings.append(ValidationFinding(
                "Lease Agreements", "Present", f"{len(lease_files)} file(s) — parse lỗi: {e}", False))
            result.mismatches.append(f"Không đọc được lease agreements: {e}")
    else:
        result.findings.append(ValidationFinding(
            "Lease Agreements", "Not Present", "Không có file lease", True))
        result.notes.append("Không có lease agreements — phù hợp với rental income $0 trong XML")

    result.status = "pass" if not result.mismatches and not result.missing_docs else \
                    "missing" if result.missing_docs and not result.mismatches else "mismatch"
    console.print(f"\n[{'green' if result.status=='pass' else 'red'}]{'✅ PASS' if result.status=='pass' else '❌ ISSUES'}[/] — REO Agent")
    state.reo_result = result
    return state
