import xml.etree.ElementTree as ET
import json
from dataclasses import dataclass, field

NS = {
    "m":    "http://www.mismo.org/residential/2009/schemas",
    "ULAD": "http://www.datamodelextension.org/Schema/ULAD",
    "DU":   "http://www.datamodelextension.org/Schema/DU",
    "xlink":"http://www.w3.org/1999/xlink",
}


def _t(el, path):
    node = el.find(path, NS)
    return (node.text or "").strip() if node is not None else ""

def _b(el, path):
    return _t(el, path).lower() == "true"

def _f(el, path):
    try: return float(_t(el, path))
    except: return 0.0

def _i(el, path):
    try: return int(_t(el, path))
    except: return 0


@dataclass
class Borrower:
    role_label: str = ""
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    dob: str = ""
    ssn: str = ""
    email: str = ""
    phone: str = ""
    marital_status: str = ""
    dependent_count: int = 0
    citizenship: str = ""
    gender: str = ""
    race: str = ""
    ethnicity: str = ""
    bankruptcy: bool = False
    outstanding_judgments: bool = False
    party_to_lawsuit: bool = False
    prior_foreclosure: bool = False
    intent_to_occupy: bool = False
    current_address: str = ""
    current_city: str = ""
    current_state: str = ""
    current_zip: str = ""
    residency_basis: str = ""
    residency_months: int = 0


@dataclass
class Asset:
    asset_label: str = ""
    holder: str = ""
    account_id: str = ""
    asset_type: str = ""
    amount: float = 0.0
    associated_borrowers: list = field(default_factory=list)


@dataclass
class Employment:
    borrower_label: str = ""
    borrower_name: str = ""
    employer_name: str = ""
    employer_address: str = ""
    employer_city: str = ""
    employer_state: str = ""
    employer_zip: str = ""
    employer_phone: str = ""
    position: str = ""
    classification: str = ""
    self_employed: bool = False
    ownership_interest: str = ""
    start_date: str = ""
    status: str = ""
    months_in_line: int = 0
    income_items: list = field(default_factory=list)
    monthly_income_total: float = 0.0
    foreign_income: bool = False
    seasonal_income: bool = False


@dataclass
class RealEstateOwned:
    asset_label: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    current_usage: str = ""
    usage_type: str = ""
    estimated_value: float = 0.0
    disposition: str = ""
    subject_indicator: bool = False
    maintenance_expense: float = 0.0
    rental_income_gross: float = 0.0
    associated_borrowers: list = field(default_factory=list)


@dataclass
class XMLBaseline:
    borrowers: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    employments: list = field(default_factory=list)
    real_estate_owned: list = field(default_factory=list)


def parse_xml(xml_path: str) -> XMLBaseline:
    """Parse MISMO XML → XMLBaseline (typed dataclasses)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    baseline = XMLBaseline()

    # Relationship map: ASSET_x → [BORROWER_y]
    rel_map: dict = {}
    for rel in root.findall(".//m:RELATIONSHIP", NS):
        frm = rel.get("{http://www.w3.org/1999/xlink}from", "")
        to  = rel.get("{http://www.w3.org/1999/xlink}to", "")
        if frm.startswith("ASSET_") and to.startswith("BORROWER_"):
            rel_map.setdefault(frm, []).append(to)

    # ── BORROWERS ─────────────────────────────────────────────────────────────
    for party in root.findall(".//m:PARTY", NS):
        role_el = party.find(".//m:ROLE", NS)
        if role_el is None:
            continue
        if _t(role_el, "m:ROLE_DETAIL/m:PartyRoleType") != "Borrower":
            continue

        b = Borrower()
        b.role_label = role_el.get("{http://www.w3.org/1999/xlink}label", "")

        indiv = party.find("m:INDIVIDUAL", NS)
        if indiv is not None:
            b.first_name = _t(indiv, "m:NAME/m:FirstName")
            b.last_name  = _t(indiv, "m:NAME/m:LastName")
            b.full_name  = f"{b.first_name} {b.last_name}".strip()

        b.email = _t(party, ".//m:ContactPointEmailValue")
        b.phone = _t(party, ".//m:ContactPointTelephoneValue")
        b.ssn   = _t(party, ".//m:TaxpayerIdentifierValue")

        bd = party.find(".//m:BORROWER_DETAIL", NS)
        if bd is not None:
            b.dob             = _t(bd, "m:BorrowerBirthDate")
            b.marital_status  = _t(bd, "m:MaritalStatusType")
            b.dependent_count = _i(bd, "m:DependentCount")
            b.citizenship     = _t(bd, "m:CitizenshipResidencyType")
            b.intent_to_occupy = _b(bd, "m:BorrowerQualificationPrimaryBorrowerIndicator")

        decl = party.find(".//m:DECLARATION", NS)
        if decl is not None:
            b.bankruptcy            = _b(decl, "m:BankruptcyIndicator")
            b.outstanding_judgments = _b(decl, "m:OutstandingJudgmentsIndicator")
            b.party_to_lawsuit      = _b(decl, "m:PartyToLawsuitIndicator")
            b.prior_foreclosure     = _b(decl, "m:PriorPropertyForeclosureCompletedIndicator")

        demo = party.find(".//m:BORROWER_DEMOGRAPHICS", NS)
        if demo is not None:
            b.gender    = _t(demo, "m:BorrowerGenderType")
            b.ethnicity = _t(demo, ".//m:EthnicityType")
            b.race      = _t(demo, ".//m:RaceType")

        for addr in party.findall(".//m:ADDRESS", NS):
            if _t(addr, "m:AddressType") in ("Current", ""):
                b.current_address  = _t(addr, "m:AddressLineText")
                b.current_city     = _t(addr, "m:CityName")
                b.current_state    = _t(addr, "m:StateCode")
                b.current_zip      = _t(addr, "m:PostalCode")
                b.residency_basis  = _t(addr, "m:BorrowerResidencyBasisType")
                b.residency_months = _i(addr, "m:BorrowerResidencyDurationMonthsCount")
                break

        baseline.borrowers.append(b)

    label_to_name = {b.role_label: b.full_name for b in baseline.borrowers}

    # ── ASSETS ────────────────────────────────────────────────────────────────
    for asset_el in root.findall(".//m:ASSET", NS):
        if asset_el.find("m:OWNED_PROPERTY", NS) is not None:
            continue  # REO handled below
        detail = asset_el.find("m:ASSET_DETAIL", NS)
        if detail is None:
            continue

        a = Asset()
        a.asset_label = asset_el.get("{http://www.w3.org/1999/xlink}label", "")
        a.account_id  = _t(detail, "m:AssetAccountIdentifier")
        a.asset_type  = _t(detail, "m:AssetType")
        a.amount      = _f(detail, "m:AssetCashOrMarketValueAmount")
        a.associated_borrowers = rel_map.get(a.asset_label, [])
        if a.associated_borrowers:
            a.holder = label_to_name.get(a.associated_borrowers[0], a.associated_borrowers[0])
        baseline.assets.append(a)

    # ── EMPLOYMENT ────────────────────────────────────────────────────────────
    for party in root.findall(".//m:PARTY", NS):
        role_el = party.find(".//m:ROLE", NS)
        if role_el is None:
            continue
        if _t(role_el, "m:ROLE_DETAIL/m:PartyRoleType") != "Borrower":
            continue

        borrower_label = role_el.get("{http://www.w3.org/1999/xlink}label", "")
        borrower_name  = label_to_name.get(borrower_label, borrower_label)

        for employer in party.findall(".//m:EMPLOYER", NS):
            e = Employment()
            e.borrower_label    = borrower_label
            e.borrower_name     = borrower_name
            e.employer_name     = _t(employer, ".//m:FullName")
            e.position          = _t(employer, ".//m:EmploymentPositionDescription")
            e.classification    = _t(employer, ".//m:EmploymentClassificationType")
            e.self_employed     = _b(employer, ".//m:SelfEmployedIndicator")
            e.ownership_interest= _t(employer, ".//m:OwnershipInterestType")
            e.start_date        = _t(employer, ".//m:EmploymentStartDate")
            e.status            = _t(employer, ".//m:EmploymentStatusType")
            e.months_in_line    = _i(employer, ".//m:PositionMonthsCount")
            e.foreign_income    = _b(employer, ".//m:SpecialEmployerRelationshipIndicator")
            e.seasonal_income   = _b(employer, ".//m:SeasonalIncomeIndicator")

            emp_addr = employer.find(".//m:ADDRESS", NS)
            if emp_addr is not None:
                e.employer_address = _t(emp_addr, "m:AddressLineText")
                e.employer_city    = _t(emp_addr, "m:CityName")
                e.employer_state   = _t(emp_addr, "m:StateCode")
                e.employer_zip     = _t(emp_addr, "m:PostalCode")
            e.employer_phone = _t(employer, ".//m:ContactPointTelephoneValue")

            total = 0.0
            for inc in employer.findall(".//m:INCOME", NS):
                inc_type = _t(inc, "m:IncomeType")
                amount   = _f(inc, "m:IncomeMonthlyTotalAmount")
                if inc_type:
                    e.income_items.append({"type": inc_type, "amount": amount})
                    total += amount

            if not e.income_items:
                monthly = _f(employer, ".//m:EmploymentMonthlyIncomeAmount")
                if monthly:
                    e.income_items.append({"type": "Base", "amount": monthly})
                    total = monthly

            e.monthly_income_total = total
            baseline.employments.append(e)

    # ── REAL ESTATE OWNED ─────────────────────────────────────────────────────
    for asset_el in root.findall(".//m:ASSET", NS):
        op = asset_el.find("m:OWNED_PROPERTY", NS)
        if op is None:
            continue
        prop = op.find("m:PROPERTY", NS)
        if prop is None:
            continue

        r = RealEstateOwned()
        r.asset_label   = asset_el.get("{http://www.w3.org/1999/xlink}label", "")
        r.address       = _t(prop, "m:ADDRESS/m:AddressLineText")
        r.city          = _t(prop, "m:ADDRESS/m:CityName")
        r.state         = _t(prop, "m:ADDRESS/m:StateCode")
        r.zip_code      = _t(prop, "m:ADDRESS/m:PostalCode")
        r.current_usage = _t(op, "m:OWNED_PROPERTY_DETAIL/m:CurrentUsageType") or "Unknown"
        r.usage_type    = _t(op, "m:OWNED_PROPERTY_DETAIL/m:PropertyUsageType")
        r.disposition   = _t(op, "m:OWNED_PROPERTY_DETAIL/m:DispositionStatusType")
        r.subject_indicator   = _b(op, "m:OWNED_PROPERTY_DETAIL/m:ReoSubjectPropertyIndicator")
        r.maintenance_expense = _f(op, "m:OWNED_PROPERTY_DETAIL/m:MaintenanceExpenseAmount")
        r.rental_income_gross = _f(op, "m:OWNED_PROPERTY_DETAIL/m:RentalIncomeGrossAmount")

        detail = asset_el.find("m:ASSET_DETAIL", NS)
        if detail is not None:
            r.estimated_value = _f(detail, "m:AssetCashOrMarketValueAmount")

        r.associated_borrowers = rel_map.get(r.asset_label, [])
        baseline.real_estate_owned.append(r)

    return baseline


# Backwards-compatible aliases
def parse_xml_to_dict(xml_path: str) -> XMLBaseline:
    return parse_xml(xml_path)

def parse_xml_to_json(xml_path: str) -> str:
    import dataclasses
    baseline = parse_xml(xml_path)
    return json.dumps(dataclasses.asdict(baseline), indent=2, default=str)
