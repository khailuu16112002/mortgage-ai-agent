"""
File Classifier — phân loại PDF theo tên file vào 4 domain chính.
"""
from pathlib import Path
from enum import Enum


class DocType(str, Enum):
    # borrower
    DRIVER_LICENSE        = "driver_license"
    # assets
    BANK_STATEMENT        = "bank_statement"
    BROKERAGE_STATEMENT   = "brokerage_statement"
    # employment
    W2                    = "w2"
    PAYSTUB               = "paystub"
    TAX_RETURN            = "tax_return"
    BUSINESS_TAX_RETURN   = "business_tax_return"
    # real_estate_owned
    REO_DOC               = "reo_doc"
    INSURANCE             = "insurance"
    LEASE                 = "lease"
    # other
    UNKNOWN               = "unknown"


# (keyword_fragments, DocType)  — so sánh trên tên file đã lowercase + stripped
RULES: list[tuple[list[str], DocType]] = [
    (["driverslicense", "driverslicence", "driver_license", "driverslicensebecky"], DocType.DRIVER_LICENSE),
    (["bankstatement", "bank_statement", "wellsfargo", "_112625wellsfargo", "_122325wellsfargo"], DocType.BANK_STATEMENT),
    (["brokeragestatement", "brokerage_statement"], DocType.BROKERAGE_STATEMENT),
    (["business_tax_return", "businesstaxreturn", "greenwave_us_"],                DocType.BUSINESS_TAX_RETURN),
    (["taxreturn", "tax_return", "1040", "2024taxesnopassword", "2023archive",
      "20231040", "federaltax", "2024taxes"],                                      DocType.TAX_RETURN),
    (["payslip", "paystub", "pay_slip", "paysliprebecca"],                         DocType.PAYSTUB),
    (["reo documentation", "reodocumentation", "reo_documentation", "reo doc"],    DocType.REO_DOC),
    (["insurance", "clarksoninsurnace", "washingtoninsurance", "463swashington",
      "463s.washington"],                                                           DocType.INSURANCE),
    (["lease-", "leaseagreement"],                                                  DocType.LEASE),
]

# W2 handled specially (exact stem match)
W2_STEMS = {"w2", "w2(1)"}


def classify_file(filepath: str) -> DocType:
    path = Path(filepath)
    stem_lower = path.stem.lower()
    name_lower = path.name.lower()

    # Exact stem match for W2
    if stem_lower in W2_STEMS:
        return DocType.W2

    # Keyword match (strip spaces/dashes/underscores for robust matching)
    name_clean = name_lower.replace(" ", "").replace("-", "").replace("_", "")
    for keywords, doc_type in RULES:
        for kw in keywords:
            kw_clean = kw.replace(" ", "").replace("-", "").replace("_", "")
            if kw_clean in name_clean:
                return doc_type

    return DocType.UNKNOWN


def classify_directory(pdf_dir: str) -> dict:
    """Quét thư mục, trả về {DocType: [full_paths]}."""
    result: dict[DocType, list[str]] = {t: [] for t in DocType}
    for pdf in sorted(Path(pdf_dir).glob("*.pdf")):
        result[classify_file(str(pdf))].append(str(pdf))
    # Also handle .PDF uppercase
    for pdf in sorted(Path(pdf_dir).glob("*.PDF")):
        result[classify_file(str(pdf))].append(str(pdf))
    return result


ICONS = {
    DocType.DRIVER_LICENSE:      "🪪",
    DocType.BANK_STATEMENT:      "🏦",
    DocType.BROKERAGE_STATEMENT: "📈",
    DocType.W2:                  "📋",
    DocType.PAYSTUB:             "💵",
    DocType.TAX_RETURN:          "📊",
    DocType.BUSINESS_TAX_RETURN: "🏢",
    DocType.REO_DOC:             "🏠",
    DocType.INSURANCE:           "🛡️",
    DocType.LEASE:               "📜",
    DocType.UNKNOWN:             "❓",
}

DOMAIN_MAP = {
    "borrower":          [DocType.DRIVER_LICENSE],
    "assets":            [DocType.BANK_STATEMENT, DocType.BROKERAGE_STATEMENT],
    "employment":        [DocType.W2, DocType.PAYSTUB, DocType.TAX_RETURN, DocType.BUSINESS_TAX_RETURN],
    "real_estate_owned": [DocType.REO_DOC, DocType.INSURANCE, DocType.LEASE],
}


def print_classification(classified: dict) -> None:
    print("\n📂 PHÂN LOẠI FILE THEO 4 DOMAIN:")
    for domain, types in DOMAIN_MAP.items():
        print(f"\n  [{domain.upper()}]")
        found_any = False
        for t in types:
            for f in classified.get(t, []):
                print(f"    {ICONS[t]} [{t.value:25s}] {Path(f).name}")
                found_any = True
        if not found_any:
            print(f"    (không có file)")

    unknowns = classified.get(DocType.UNKNOWN, [])
    if unknowns:
        print(f"\n  [UNKNOWN] {len(unknowns)} file không nhận dạng:")
        for f in unknowns:
            print(f"    ❓ {Path(f).name}")
