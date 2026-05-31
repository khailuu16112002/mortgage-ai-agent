# 🏦 Mortgage Verification System v2.0

Multi-agent AI system for automated mortgage document verification.
Compares MISMO 3.4 XML baselines against supporting PDFs using LangGraph, GPT-4o, chunking, ONNX inference, and a FastAPI + Streamlit web interface.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        WEB DEMO (Streamlit)                      │
│  Upload │ Results │ Logs │ Chunk Preview │ Session History        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  /upload  /process  /results  /logs  /chunks  /sessions          │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                   LangGraph Pipeline                             │
│                                                                  │
│  Supervisor → Borrower → Asset → Employment → REO → Aggregator  │
│       │                                                          │
│       ├── XML Parser (MISMO 3.4)                                 │
│       ├── File Classifier (10 DocTypes)                          │
│       ├── Document Chunker (RecursiveTextSplitter)               │
│       ├── LLM File Matcher (GPT-4o semantic matching)            │
│       └── NER Pipeline (ONNX / HuggingFace / Regex fallback)    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                   Persistence Layer                              │
│  SQLite (dev) / PostgreSQL (prod) via SQLAlchemy ORM             │
│                                                                  │
│  processing_sessions │ uploaded_files │ extracted_chunks         │
│  validation_results  │ agent_logs                                │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline flow — Document Processing
```
PDF → read_pdf_smart() → RecursiveTextSplitter → DocumentChunk[]
                                                       │
                                              ┌────────▼────────┐
                                              │  DB: chunks      │
                                              └────────┬────────┘
                                                       │
                                              get_chunks_as_context()
                                                       │
                                              ┌────────▼────────┐
                                              │  GPT-4o Agent    │
                                              │  Verification    │
                                              └────────┬────────┘
                                                       │
                                              ValidationFinding[]
                                                       │
                                              ┌────────▼────────┐
                                              │  DB: results     │
                                              └─────────────────┘
```

---

## Project Structure

```
mortgage_refactored/
├── main.py                  # CLI entry point
├── graph.py                 # LangGraph pipeline builder
├── requirements.txt
├── .env.example
│
├── config/
│   ├── settings.py          # Pydantic settings (env vars)
│   └── logging_config.py    # Structured logging
│
├── agents/
│   ├── state.py             # GraphState, AgentResult, ValidationFinding
│   ├── supervisor.py        # XML parse + classify + chunk + match
│   ├── borrower_agent.py    # Driver license verification
│   ├── asset_agent.py       # Bank/brokerage statement verification
│   ├── employment_agent.py  # W2/paystub/tax return verification
│   ├── reo_agent.py         # Insurance/REO/lease verification
│   └── aggregator.py        # Final report
│
├── pipelines/
│   ├── chunking.py          # RecursiveTextSplitter + DocumentChunk
│   └── onnx_inference.py    # ONNX NER/Classifier + HF/Regex fallback
│
├── services/
│   └── file_matcher.py      # LLM-based document ↔ borrower matching
│
├── database/
│   ├── models.py            # SQLAlchemy ORM models
│   ├── engine.py            # Engine + session factory
│   └── repository.py        # Repository pattern (CRUD)
│
├── utils/
│   ├── file_classifier.py   # Rule-based PDF classification
│   ├── pdf_reader.py        # PDF text + vision extraction
│   ├── xml_parser.py        # MISMO 3.4 XML → dataclasses
│   └── xml_to_json.py       # Baseline → flat JSON facts
│
├── api/
│   └── main.py              # FastAPI application
│
├── frontend/
│   └── app.py               # Streamlit dashboard
│
└── docker/
    ├── Dockerfile
    └── docker-compose.yml
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone <repo>
cd mortgage_agent
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

### 3. Run — CLI

```bash
python main.py --xml data/sample.xml --pdfs data/pdfs/
```

### 4. Run — Web Demo (localhost)

**Terminal 1 — API server:**
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
# Docs: http://localhost:8000/docs
```

**Terminal 2 — Streamlit dashboard:**
```bash
streamlit run frontend/app.py
# Opens: http://localhost:8501
```

### 5. Run — Docker

```bash
cd docker
OPENAI_API_KEY=sk-... docker-compose up --build
# API:      http://localhost:8000
# Frontend: http://localhost:8501
```

---

## API Reference

### Upload documents
```bash
curl -X POST http://localhost:8000/upload \
  -F "xml_file=@data/sample.xml" \
  -F "pdf_files=@data/pdfs/driver_license.pdf" \
  -F "pdf_files=@data/pdfs/bank_statement.pdf"
# Returns: {"session_id": "abc123-..."}
```

### Start processing
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc123-..."}'
```

### Get results
```bash
curl http://localhost:8000/results/abc123-...
```

### Get logs
```bash
curl http://localhost:8000/logs/abc123-...
```

### Preview chunks
```bash
curl "http://localhost:8000/chunks/abc123-...?domain=borrower"
```

---

## Database Schema

| Table | Description |
|---|---|
| `processing_sessions` | One row per verification run |
| `uploaded_files` | Each uploaded XML/PDF with doc_type, OCR text, match result |
| `extracted_chunks` | Document chunks with metadata (page, domain, tokens) |
| `validation_results` | Per-field PASS/FAIL/MISSING with expected vs extracted values |
| `agent_logs` | Timestamped log entries per agent per session |

---

## Chunking Configuration

| Setting | Default | Description |
|---|---|---|
| `CHUNK_SIZE` | 800 | Target tokens per chunk |
| `CHUNK_OVERLAP` | 150 | Overlap between consecutive chunks |
| `MIN_CHUNK_LENGTH` | 50 | Discard chunks shorter than this |
| `MAX_CHUNKS_PER_DOC` | 100 | Cap per document |

---

## ONNX Inference

Set `ONNX_ENABLED=true` and place exported models in `ONNX_MODEL_DIR`:

```
models/onnx/
├── ner_model.onnx
├── classifier_model.onnx
├── config.json
├── tokenizer_config.json
└── vocab.txt
```

To export a HuggingFace model:
```python
from pipelines.onnx_inference import export_model_to_onnx
export_model_to_onnx("dslim/bert-base-NER", "./models/onnx", task="ner")
```

**Fallback chain:** ONNX → HuggingFace Transformers → SimpleRegexNER (zero-dependency)

---

## LLM File Matching

Each document is matched to borrowers/accounts using:
1. **NER extraction** — pulls names, dates, money, addresses from document text
2. **LLM reasoning** — GPT-4o compares entities against XML profile
3. **Confidence scoring** — 0.0–1.0 with explanation

Example output:
```json
{
  "matched": true,
  "confidence": 0.94,
  "reason": "Name 'Patrick Durst' and address '463 S Washington St' both found in document",
  "matched_fields": ["borrower_name", "address"],
  "source_doc": "driver_license.pdf",
  "target_entity": "Patrick Durst"
}
```

---

## Environment Variables

See `.env.example` for all options. Minimum required:
```
OPENAI_API_KEY=sk-...
```
