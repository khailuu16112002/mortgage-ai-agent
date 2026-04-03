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

## Chạy

```bash
# Cách 1: tham số trực tiếp
python main.py --xml data/Patrick_Durst.xml --pdfs data/pdf

# Cách 2: interactive
python main.py
```

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
