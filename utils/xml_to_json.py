"""
xml_to_json.py
Chuyển XMLBaseline → JSON cấu trúc phẳng, tối ưu cho việc so sánh với PDF.
"""
import json
from pathlib import Path
from utils.xml_parser import XMLBaseline, parse_xml


def baseline_to_structured_json(baseline: XMLBaseline) -> dict:
    """Tạo JSON có cấu trúc 4 domain rõ ràng."""
    return {
        "source": "MISMO XML 3.4",
        "borrower": [
            {
                "role_label":       b.role_label,
                "full_name":        b.full_name,
                "first_name":       b.first_name,
                "last_name":        b.last_name,
                "dob":              b.dob,
                "ssn_last4":        b.ssn[-4:] if len(b.ssn) >= 4 else b.ssn,
                "email":            b.email,
                "phone":            b.phone,
                "marital_status":   b.marital_status,
                "dependent_count":  b.dependent_count,
                "citizenship":      b.citizenship,
                "gender":           b.gender,
                "race":             b.race,
                "ethnicity":        b.ethnicity,
                "bankruptcy":       b.bankruptcy,
                "outstanding_judgments": b.outstanding_judgments,
                "party_to_lawsuit": b.party_to_lawsuit,
                "prior_foreclosure":b.prior_foreclosure,
                "intent_to_occupy": b.intent_to_occupy,
                "current_address": {
                    "street": b.current_address,
                    "city":   b.current_city,
                    "state":  b.current_state,
                    "zip":    b.current_zip,
                    "full":   f"{b.current_address}, {b.current_city}, {b.current_state} {b.current_zip}"
                },
                "residency_basis":  b.residency_basis,
                "residency_months": b.residency_months,
            }
            for b in baseline.borrowers
        ],
        "assets": {
            "summary": {
                "total_accounts": len(baseline.assets),
                "total_amount":   round(sum(a.amount for a in baseline.assets), 2),
                "by_type": {
                    t: {
                        "count": sum(1 for a in baseline.assets if a.asset_type == t),
                        "total": round(sum(a.amount for a in baseline.assets if a.asset_type == t), 2)
                    }
                    for t in sorted({a.asset_type for a in baseline.assets})
                }
            },
            "accounts": [
                {
                    "asset_label":   a.asset_label,
                    "holder":        a.holder,
                    "account_id":    a.account_id,
                    "account_last4": a.account_id.replace("-", "").replace(" ", "")[-4:],
                    "asset_type":    a.asset_type,
                    "amount":        a.amount,
                    "associated_borrowers": a.associated_borrowers,
                }
                for a in baseline.assets
            ]
        },
        "employment": [
            {
                "borrower_label": e.borrower_label,
                "borrower_name":  e.borrower_name,
                "employer_name":  e.employer_name,
                "employer_address": {
                    "street": e.employer_address,
                    "city":   e.employer_city,
                    "state":  e.employer_state,
                    "zip":    e.employer_zip,
                    "full":   f"{e.employer_address}, {e.employer_city}, {e.employer_state} {e.employer_zip}"
                },
                "employer_phone":    e.employer_phone,
                "position":          e.position,
                "classification":    e.classification,
                "self_employed":     e.self_employed,
                "ownership_interest":e.ownership_interest,
                "start_date":        e.start_date,
                "status":            e.status,
                "months_in_line":    e.months_in_line,
                "income": {
                    "items":         e.income_items,
                    "monthly_total": e.monthly_income_total,
                    "annual_total":  round(e.monthly_income_total * 12, 2),
                },
                "foreign_income":  e.foreign_income,
                "seasonal_income": e.seasonal_income,
            }
            for e in baseline.employments
        ],
        "real_estate_owned": [
            {
                "asset_label": r.asset_label,
                "address": {
                    "street": r.address,
                    "city":   r.city,
                    "state":  r.state,
                    "zip":    r.zip_code,
                    "full":   f"{r.address}, {r.city}, {r.state} {r.zip_code}"
                },
                "current_usage":    r.current_usage,
                "usage_type":       r.usage_type,
                "estimated_value":  r.estimated_value,
                "disposition":      r.disposition,
                "subject_property": r.subject_indicator,
                "monthly_expenses": {
                    "maintenance":   r.maintenance_expense,
                    "rental_income": r.rental_income_gross,
                    "net_expense":   round(r.maintenance_expense - r.rental_income_gross, 2),
                },
                "associated_borrowers": r.associated_borrowers,
            }
            for r in baseline.real_estate_owned
        ]
    }


def baseline_to_flat_facts(baseline: XMLBaseline) -> dict:
    """Tạo dict phẳng {key: value} dùng để so sánh trực tiếp với PDF."""
    facts = {}

    for b in baseline.borrowers:
        pfx = f"borrower.{b.role_label}"
        facts[f"{pfx}.full_name"]       = b.full_name
        facts[f"{pfx}.dob"]             = b.dob
        facts[f"{pfx}.ssn_last4"]       = b.ssn[-4:] if len(b.ssn) >= 4 else b.ssn
        facts[f"{pfx}.email"]           = b.email
        facts[f"{pfx}.phone"]           = b.phone
        facts[f"{pfx}.marital_status"]  = b.marital_status
        facts[f"{pfx}.citizenship"]     = b.citizenship
        facts[f"{pfx}.gender"]          = b.gender
        facts[f"{pfx}.current_address"] = f"{b.current_address}, {b.current_city}, {b.current_state} {b.current_zip}"
        facts[f"{pfx}.residency_basis"] = b.residency_basis
        facts[f"{pfx}.bankruptcy"]      = b.bankruptcy
        facts[f"{pfx}.intent_to_occupy"]= b.intent_to_occupy

    for a in baseline.assets:
        pfx = f"assets.{a.account_id}"
        facts[f"{pfx}.holder"]     = a.holder
        facts[f"{pfx}.asset_type"] = a.asset_type
        facts[f"{pfx}.amount"]     = a.amount

    for e in baseline.employments:
        pfx = f"employment.{e.borrower_label}"
        facts[f"{pfx}.employer_name"]  = e.employer_name
        facts[f"{pfx}.position"]       = e.position
        facts[f"{pfx}.self_employed"]  = e.self_employed
        facts[f"{pfx}.start_date"]     = e.start_date
        facts[f"{pfx}.status"]         = e.status
        facts[f"{pfx}.monthly_total"]  = e.monthly_income_total
        for item in e.income_items:
            facts[f"{pfx}.income.{item['type'].lower()}"] = item["amount"]

    for r in baseline.real_estate_owned:
        pfx = f"reo.{r.asset_label}"
        facts[f"{pfx}.address"]         = f"{r.address}, {r.city}, {r.state} {r.zip_code}"
        facts[f"{pfx}.current_usage"]   = r.current_usage
        facts[f"{pfx}.estimated_value"] = r.estimated_value
        facts[f"{pfx}.maintenance"]     = r.maintenance_expense
        facts[f"{pfx}.rental_income"]   = r.rental_income_gross
        facts[f"{pfx}.disposition"]     = r.disposition

    return facts


def compare_facts(xml_facts: dict, pdf_facts: dict,
                  numeric_tolerance: float = 0.05) -> dict:
    result = {"matched": [], "mismatched": [], "missing": [], "extra": []}
    for key in sorted(set(xml_facts) | set(pdf_facts)):
        xv = xml_facts.get(key)
        pv = pdf_facts.get(key)
        if xv is None:
            result["extra"].append(key)
        elif pv is None:
            result["missing"].append(key)
        elif isinstance(xv, (int, float)) and isinstance(pv, (int, float)):
            tol = max(abs(float(xv)) * numeric_tolerance, 50)
            if abs(float(xv) - float(pv)) <= tol:
                result["matched"].append({"key": key, "xml": xv, "pdf": pv})
            else:
                result["mismatched"].append({"key": key, "xml": xv, "pdf": pv,
                    "diff": round(float(pv) - float(xv), 2)})
        else:
            if str(xv).strip().lower() == str(pv).strip().lower():
                result["matched"].append({"key": key, "xml": xv, "pdf": pv})
            else:
                result["mismatched"].append({"key": key, "xml": xv, "pdf": pv})
    return result


def save_baseline_json(baseline: XMLBaseline, output_path: str) -> None:
    data = baseline_to_structured_json(baseline)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✓ Saved: {output_path}")


def save_flat_facts(baseline: XMLBaseline, output_path: str) -> None:
    facts = baseline_to_flat_facts(baseline)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)
    print(f"✓ Saved: {output_path}")


if __name__ == "__main__":
    import sys
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "data/Patrick_Durst.xml"
    out_dir  = sys.argv[2] if len(sys.argv) > 2 else "data"
    baseline = parse_xml(xml_path)
    save_baseline_json(baseline, f"{out_dir}/baseline.json")
    save_flat_facts(baseline,    f"{out_dir}/baseline_facts.json")
