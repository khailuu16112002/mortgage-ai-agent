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

py -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt

cp .env
# Mở .env → điền OPEN_AI_KEY
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
py main.py --xml data/Patrick_Durst.xml --pdfs data/pdf

# Cách 2: interactive
py main.py
```

---

## XML Baseline — Patrick_Durst.xml

### Domain 1: Borrower
### Domain 2: Assets
### Domain 3: Employment
### Domain 4: Real Estate Owned

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
