# 🏦 Mortgage Verification Agent

LangGraph multi-agent pipeline xác thực hồ sơ vay thế chấp.
Parse XML baseline (MISMO 3.4) → so sánh với PDF documents theo **4 domain chính**.

---

## 4 Domain chính

| Domain | Fields từ XML | PDF cần upload |
|---|---|---|
| **borrower** | full_name, DOB, SSN, email, phone, marital_status, citizenship, current_address, gender | Driver's License |
| **assets** | holder, account_id, asset_type, amount (11 tài khoản) | Bank Statements, Brokerage Statements |
| **employment** | employer_name, position, self_employed, start_date, income_items, monthly_income_total | Business Tax Return (Patrick), W-2 + Paystub (Rebecca), Personal Tax Returns |
| **real_estate_owned** | address, estimated_value, current_usage, maintenance_expense, rental_income_gross | REO Documentation, Insurance, Lease Agreements |

---

## Kiến trúc Agent

```
SUPERVISOR AGENT
 ├── Parse XML → 4 domain objects
 └── Phân loại PDF → mapping vào domain
        │
 ┌──────┴──────────────────────────────────┐
 ▼           ▼            ▼                ▼
BORROWER   ASSET     EMPLOYMENT        REO AGENT
 Agent     Agent      Agent
 (DL)   (Bank+Brok) (W2+Tax+Pay)   (REO+Ins+Lease)
        │
        ▼
   AGGREGATOR
   (Báo cáo cuối)
```

---

## Cài đặt

```bash
cd mortgage_agent

python -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt

cp .env.example .env
# Mở .env → điền ANTHROPIC_API_KEY
```

---

## Chuẩn bị dữ liệu

```
mortgage_agent/
└── data/
    ├── Patrick_Durst.xml              ← XML baseline
    └── pdfs/
        │
        │ # BORROWER domain
        ├── driverslicensebeckyandpatrick.pdf
        │
        │ # ASSETS domain
        ├── bankstatement_2025-11-28_211.pdf
        ├── bankstatement_2025-12-31_211.pdf
        ├── _112625wellsfargo.pdf
        ├── _122325wellsfargo.pdf
        ├── brokeragestatement_2025-11-30_*.pdf
        ├── brokeragestatement_2025-12-31_*.pdf
        │
        │ # EMPLOYMENT domain
        ├── W2.pdf
        ├── W2(1).pdf
        ├── 12.31.25paysliprebeccadurst..pdf
        ├── 1.15.26paysliprebeccadurst.pdf
        ├── greenwave_us_2024_archivetaxreturnnopassword.pdf
        ├── greenwave_us_2023_archivetaxreturnnopassword.pdf
        ├── Business_Tax_Return_*.pdf
        ├── 2024taxesnopasswordfederal.pdf
        ├── 20231040patrickbeckydurst.pdf
        │
        │ # REAL ESTATE OWNED domain
        ├── REO Documentation.pdf
        ├── REO Documentation_ 1.pdf
        ├── 463swashingtoninsurance.pdf
        ├── washingtoninsurance.pdf
        ├── clarksoninsurnace.pdf
        ├── lease-daniellebourn-20250824.pdf
        └── lease-sarahoward-20250827.pdf
```

---

## Chạy

```bash
# Cách 1: tham số trực tiếp
python main.py --xml data/Patrick_Durst.xml --pdfs data/pdf

# Cách 2: interactive
python main.py
```

---

## XML Baseline — Patrick_Durst.xml

### Domain 1: Borrower
| Field | Patrick | Rebecca |
|---|---|---|
| DOB | 1991-02-16 | 1989-05-06 |
| SSN (last 4) | …4535 | …7643 |
| Email | pdpwns@gmail.com | beckydurst42@gmail.com |
| Phone | 719-502-7033 | 303-815-8435 |
| Marital | Married | Married |
| Citizenship | USCitizen | USCitizen |
| Gender | Male | Female |
| Address | 463 S. Washington St, Denver CO 80209 | same |

### Domain 2: Assets — Total $2,180,772
| Holder | Type | Account | Amount |
|---|---|---|---|
| Charles Schwab Bank | CheckingAccount | 440024861211 | $53,964 |
| Wells Fargo | CheckingAccount | 2151035017 | $19,196 |
| Wells Fargo | CheckingAccount | 8151130302 | $4,991 |
| Charles Schwab | TrustAccount | 8824-4187 | $69,426 |
| Charles Schwab | Stock | 3637-3371 | $802,000 |
| Charles Schwab IRA | Stock | 3690-5397 | $76,937 |
| Charles Schwab Roth 401k | Stock | 5545-8974 | $189,706 |
| Charles Schwab Roth IRA | Stock | 6312-6899 | $15,373 |
| Fidelity | Stock | 510 | $436,767 |
| Fidelity | Stock | 907 | $21,751 |
| Fidelity | Stock | 963 | $490,661 |

### Domain 3: Employment
| | Patrick | Rebecca |
|---|---|---|
| Employer | Greenwave Financial Planning LLC | Janus Henderson Investors |
| Address | 2305 E Arapahoe Rd, Littleton CO | 151 Detroit St, Denver CO |
| Position | Owner | Director |
| Self-Employed | Yes (≥25% ownership) | No |
| Start Date | 2018-04-01 | 2018-01-01 |
| Income | $27,000/mo (Base) | $23,108/mo Base + $29,553/mo Commissions |

### Domain 4: Real Estate Owned
| Property | Usage | Est. Value | Maintenance | Rental |
|---|---|---|---|---|
| 463 S. Washington St, Denver CO 80209 | PrimaryResidence | $120,000 | $664/mo | $0 |
| 7242318 1st Ave, San Jose CA 95132 | Investment/SecondHome | $500,000 | $15,000/mo | $0 |

---

## Cấu trúc project

```
mortgage_agent/
├── main.py                    ← Entry point
├── graph.py                   ← LangGraph pipeline
├── requirements.txt
├── .env
├── agents/
│   ├── state.py               ← GraphState + 4 domain AgentResult
│   ├── supervisor.py          ← Parse XML + phân loại PDF
│   ├── borrower_agent.py      ← Validate domain: borrower
│   ├── asset_agent.py         ← Validate domain: assets
│   ├── employment_agent.py    ← Validate domain: employment
│   ├── reo_agent.py           ← Validate domain: real_estate_owned
│   └── aggregator.py          ← Báo cáo cuối
└── utils/
    ├── xml_parser.py          ← MISMO XML → 4 domain dataclasses
    ├── pdf_reader.py          ← PDF → base64 cho Anthropic API
    └── file_classifier.py     ← Phân loại PDF theo tên file
```
