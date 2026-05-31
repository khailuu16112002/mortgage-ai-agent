"""
Streamlit Web Demo — Mortgage Verification Dashboard
Run: streamlit run frontend/app.py
"""
import streamlit as st
import requests
import time
from pathlib import Path
from datetime import datetime

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Mortgage Verification System",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
  code, .stCode { font-family: 'IBM Plex Mono', monospace; }
  .block-container { padding: 1.5rem 2rem; }

  .metric-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 1.2rem; text-align: center;
  }
  .metric-card .value { font-size: 2rem; font-weight: 700; }
  .metric-card .label { font-size: 0.8rem; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
  .pass  { color: #3fb950; }
  .fail  { color: #f85149; }
  .missing { color: #d29922; }

  .status-badge {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.5px;
  }
  .badge-pass    { background:#1a4a1f; color:#3fb950; border:1px solid #3fb950; }
  .badge-fail    { background:#4a1a1a; color:#f85149; border:1px solid #f85149; }
  .badge-missing { background:#4a3a0a; color:#d29922; border:1px solid #d29922; }
  .badge-processing { background:#1a2a4a; color:#58a6ff; border:1px solid #58a6ff; }

  /* Missing docs warning box */
  .missing-box {
    background: #1e1a0a;
    border: 1px solid #d29922;
    border-left: 4px solid #d29922;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin: 1rem 0;
  }
  .missing-box h4 { color: #d29922; margin: 0 0 0.5rem 0; font-size: 1rem; }
  .missing-item {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 0; border-bottom: 1px solid #2a2510;
    font-size: 0.85rem; color: #c9a227;
  }
  .missing-item:last-child { border-bottom: none; }
  .missing-icon { font-size: 1rem; }

  .reupload-hint {
    background: #0d1e1e; border: 1px solid #238636;
    border-radius: 6px; padding: 0.8rem 1rem; margin-top: 0.8rem;
    font-size: 0.82rem; color: #3fb950;
  }

  .finding-row {
    display: flex; align-items: center; gap: 0;
    padding: 6px 0; border-bottom: 1px solid #21262d;
    font-size: 0.83rem;
  }
  .finding-row:last-child { border-bottom: none; }

  .chunk-card {
    background:#161b22; border-left:3px solid #30363d;
    padding:0.8rem 1rem; margin:0.5rem 0;
    border-radius:0 6px 6px 0; font-size:0.85rem;
    font-family:'IBM Plex Mono',monospace;
  }
  .log-entry {
    padding:4px 8px; margin:2px 0; border-radius:4px;
    font-size:0.8rem; font-family:'IBM Plex Mono',monospace;
  }
  .log-info    { background:#1a1f2e; color:#58a6ff; }
  .log-warning { background:#2e2a1a; color:#d29922; }
  .log-error   { background:#2e1a1a; color:#f85149; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏦 MortgageVerify")
    st.markdown("---")
    page = st.radio("Navigation", [
        "📤 Upload & Process",
        "📊 Results",
        "📋 Agent Logs",
        "🔍 Chunk Preview",
        "📅 Session History",
    ], label_visibility="collapsed")
    st.markdown("---")
    try:
        r = requests.get(f"{API_BASE}/health", timeout=2)
        st.success("API Online ✓", icon="🟢") if r.status_code == 200 else st.error("API Error", icon="🔴")
    except Exception:
        st.error("API Offline", icon="🔴")
        st.caption("Start: `uvicorn api.main:app --port 8000`")
    st.markdown("---")
    st.caption("v2.0.0 | Multi-Agent System")


# ── Helpers ────────────────────────────────────────────────────────────────────
def badge(status: str) -> str:
    cls = {
        "PASS": "badge-pass", "FAIL": "badge-fail",
        "MISSING": "badge-missing", "PROCESSING": "badge-processing",
        "COMPLETED": "badge-pass", "FAILED": "badge-fail",
        "CREATED": "badge-processing",
    }.get((status or "").upper(), "badge-missing")
    return f'<span class="status-badge {cls}">{status}</span>'


def api_get(path: str):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Không kết nối được API. Server đang chạy chưa?")
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


# Doc type → tên thân thiện + file cần cung cấp
DOC_TYPE_LABELS = {
    "driver_license":     ("Chứng minh nhân dân / Bằng lái xe",   "driver_license.pdf"),
    "bank_statement":     ("Sao kê ngân hàng",                     "bank_statement.pdf"),
    "brokerage_statement":("Sao kê tài khoản môi giới",            "brokerage_statement.pdf"),
    "w2":                 ("Mẫu W-2 (Thu nhập)",                   "w2_form.pdf"),
    "paystub":            ("Phiếu lương (Paystub)",                 "paystub.pdf"),
    "tax_return":         ("Tờ khai thuế cá nhân",                 "tax_return.pdf"),
    "business_tax":       ("Tờ khai thuế doanh nghiệp",            "business_tax.pdf"),
    "insurance":          ("Hợp đồng bảo hiểm BĐS",               "insurance.pdf"),
    "lease_agreement":    ("Hợp đồng thuê nhà",                    "lease_agreement.pdf"),
    "reo":                ("Tài liệu bất động sản (REO)",          "reo_document.pdf"),
}

DOMAIN_REQUIRED_DOCS = {
    "borrower":   ["driver_license"],
    "asset":      ["bank_statement", "brokerage_statement"],
    "employment": ["w2", "paystub", "tax_return"],
    "reo":        ["insurance", "lease_agreement"],
}


def render_missing_docs_panel(results_by_domain: dict, uploaded_doc_types: list,
                               missing_files_to_reupload: list | None = None):
    """Hiển thị danh sách file cần upload lại dựa vào missing_files_to_reupload từ API."""

    # Ưu tiên dùng danh sách chính xác từ agent
    if missing_files_to_reupload:
        st.markdown("---")
        st.markdown(f"""
<div class=\"missing-box\">
  <h4>📋 {len(missing_files_to_reupload)} File Cần Upload Lại</h4>
  <p style=\"color:#8b949e;font-size:0.82rem;margin:0 0 0.8rem\">
    Các file dưới đây không tìm thấy hoặc không đọc được — vui lòng upload lại:
  </p>
""", unsafe_allow_html=True)

        for i, item in enumerate(missing_files_to_reupload, 1):
            file_type   = item.get("file_type", "—")
            reason      = item.get("reason", "—")
            suggested   = item.get("suggested_name", "—")
            st.markdown(f"""
  <div class=\"missing-item\">
    <span class=\"missing-icon\">⚠️</span>
    <span>
      <b>{i}. {file_type}</b><br>
      <span style=\"color:#8b949e;font-size:0.8rem\">{reason}</span><br>
      <span style=\"font-family:monospace;font-size:0.75rem;color:#c9a227\">📎 {suggested}</span>
    </span>
  </div>""", unsafe_allow_html=True)

        st.markdown("""
  <div class=\"reupload-hint\">
    💡 <b>Hướng dẫn:</b> Quay lại tab <b>📤 Upload &amp; Process</b>,
    upload lại các file còn thiếu cùng XML baseline, rồi nhấn
    <b>Upload &amp; Start Processing</b>.
  </div>
</div>
""", unsafe_allow_html=True)
        return

    # Fallback: phân tích từ findings nếu không có danh sách từ API
    missing_by_domain: dict[str, list[str]] = {}
    for domain, findings in results_by_domain.items():
        missing_fields = [f for f in findings if f.get("is_missing") or f.get("status") == "MISSING"]
        if missing_fields:
            missing_by_domain[domain] = [f["field_name"] for f in missing_fields]

    if not missing_by_domain:
        return

    missing_doc_types: list[tuple] = []
    for domain, fields in missing_by_domain.items():
        required = DOMAIN_REQUIRED_DOCS.get(domain, [])
        for dt in required:
            label, sample_name = DOC_TYPE_LABELS.get(dt, (dt, dt + ".pdf"))
            already_uploaded = dt in [u.lower().replace(" ", "_") for u in uploaded_doc_types]
            if not already_uploaded:
                missing_doc_types.append((domain, dt, label, sample_name))

    st.markdown("---")
    items_html = ""
    for domain, dt, label, sample in missing_doc_types:
        domain_icon = {"borrower": "👤", "asset": "🏦", "employment": "💼", "reo": "🏠"}.get(domain, "📄")
        items_html += f"""
        <div class=\"missing-item\">
          <span class=\"missing-icon\">{domain_icon}</span>
          <span><b>{label}</b> &nbsp;<span style=\"color:#8b949e;font-size:0.78rem\">({domain.upper()})</span></span>
          <span style=\"margin-left:auto;font-family:monospace;font-size:0.75rem;color:#8b949e\">{sample}</span>
        </div>"""

    missing_fields_summary = ""
    for domain, fields in missing_by_domain.items():
        missing_fields_summary += f"<li><b>{domain.upper()}:</b> {', '.join(fields[:5])}"
        if len(fields) > 5:
            missing_fields_summary += f" +{len(fields)-5} trường khác"
        missing_fields_summary += "</li>"

    st.markdown(f"""
<div class=\"missing-box\">
  <h4>⚠️ Phát hiện {len(missing_by_domain)} nhóm tài liệu thiếu dữ liệu</h4>
  <ul style=\"color:#c9a227;font-size:0.82rem;margin:0 0 0.8rem 1rem;padding:0\">
    {missing_fields_summary}
  </ul>
  <p style=\"color:#a08020;font-size:0.82rem;margin:0 0 0.5rem\"><b>📎 Tài liệu cần bổ sung:</b></p>
  {items_html if items_html else '<div class=\"missing-item\">Đã upload đủ — hãy kiểm tra nội dung file</div>'}
  <div class=\"reupload-hint\">
    💡 <b>Hướng dẫn:</b> Quay lại tab <b>📤 Upload &amp; Process</b>, upload lại file còn thiếu.
  </div>
</div>
""", unsafe_allow_html=True)


# ── Page: Upload & Process ─────────────────────────────────────────────────────
if page == "📤 Upload & Process":
    st.markdown("## 📤 Upload Tài Liệu Vay Thế Chấp")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("### XML Baseline")
        xml_file = st.file_uploader("File XML chuẩn MISMO 3.4", type=["xml"], key="xml")
        if xml_file:
            st.success(f"✓ {xml_file.name} ({xml_file.size:,} bytes)")

    with col2:
        st.markdown("### Tài Liệu PDF")
        pdf_files = st.file_uploader(
            "Các file PDF (có thể chọn nhiều)", type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True, key="pdfs"
        )
        if pdf_files:
            for f in pdf_files:
                st.markdown(f"- `{f.name}` ({f.size:,} bytes)")

    # Checklist tài liệu cần thiết
    with st.expander("📋 Danh sách tài liệu cần chuẩn bị", expanded=False):
        cols = st.columns(2)
        docs = list(DOC_TYPE_LABELS.values())
        for i, (label, sample) in enumerate(docs):
            with cols[i % 2]:
                st.markdown(f"- **{label}** `{sample}`")

    st.markdown("---")

    if xml_file and pdf_files:
        if st.button("🚀 Upload & Bắt đầu xác minh", type="primary", use_container_width=True):
            with st.spinner("Đang upload..."):
                try:
                    files = [("xml_file", (xml_file.name, xml_file.getvalue(), "application/xml"))]
                    for pf in pdf_files:
                        files.append(("pdf_files", (pf.name, pf.getvalue(), "application/pdf")))

                    r = requests.post(f"{API_BASE}/upload", files=files, timeout=120)
                    r.raise_for_status()
                    upload_data = r.json()
                    session_id = upload_data["session_id"]
                    st.session_state["last_session_id"] = session_id
                    st.success(f"✓ Upload thành công! Session: `{session_id}`")

                    pr = requests.post(f"{API_BASE}/process", json={"session_id": session_id}, timeout=30)
                    pr.raise_for_status()
                    st.info("⚙️ Đang xử lý...")

                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    max_wait, elapsed, poll = 300, 0, 3

                    while elapsed < max_wait:
                        time.sleep(poll)
                        elapsed += poll
                        result = api_get(f"/results/{session_id}")
                        if result:
                            status = result.get("status", "")
                            progress_bar.progress(min(elapsed / max_wait, 0.95))
                            status_text.markdown(f"Trạng thái: **{status}** | {elapsed}s")
                            if status in ("COMPLETED", "FAILED"):
                                progress_bar.progress(1.0)
                                if status == "COMPLETED":
                                    overall = result.get("overall_status", "?")
                                    s = result.get("summary", {})
                                    st.success(f"✅ Hoàn tất! Kết quả tổng: **{overall}**")
                                    c1, c2, c3, c4 = st.columns(4)
                                    c1.metric("Tổng kiểm tra", s.get("total", 0))
                                    c2.metric("✅ Pass", s.get("pass", 0))
                                    c3.metric("❌ Fail", s.get("fail", 0))
                                    c4.metric("⚠️ Missing", s.get("missing", 0))
                                    st.markdown("👉 Xem chi tiết tại tab **📊 Results**")
                                else:
                                    st.error("❌ Xử lý thất bại. Kiểm tra tab **📋 Agent Logs**.")
                                break
                    else:
                        st.warning("Đang xử lý lâu hơn dự kiến. Kiểm tra tab Results sau.")

                except requests.exceptions.ConnectionError:
                    st.error("Không kết nối được API. Hãy chạy server trước!")
                except Exception as e:
                    st.error(f"Lỗi: {e}")
    else:
        st.info("Vui lòng chọn cả file XML và ít nhất 1 file PDF.")


# ── Page: Results ─────────────────────────────────────────────────────────────
elif page == "📊 Results":
    st.markdown("## 📊 Kết Quả Xác Minh")

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("last_session_id", ""),
        placeholder="Nhập Session ID...",
    )

    if session_id:
        col_refresh, _ = st.columns([1, 5])
        with col_refresh:
            if st.button("🔄 Refresh"):
                st.rerun()

        data = api_get(f"/results/{session_id}")
        if not data:
            st.stop()

        status  = data.get("status", "?")
        overall = data.get("overall_status", "")
        pt      = data.get("processing_time_sec")
        summary = data.get("summary", {})
        results_by_domain = data.get("results_by_domain", {})
        missing_files_to_reupload = data.get("missing_files_to_reupload", [])

        # ── Metric cards ───────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""<div class="metric-card">
                <div class="value">{summary.get('total',0)}</div>
                <div class="label">Tổng kiểm tra</div></div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class="metric-card">
                <div class="value pass">{summary.get('pass',0)}</div>
                <div class="label">✅ Pass</div></div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class="metric-card">
                <div class="value fail">{summary.get('fail',0)}</div>
                <div class="label">❌ Fail</div></div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""<div class="metric-card">
                <div class="value missing">{summary.get('missing',0)}</div>
                <div class="label">⚠️ Missing</div></div>""", unsafe_allow_html=True)

        # ── Status bar ─────────────────────────────────────────────────────────
        st.markdown("<div style='margin-top:1rem'>", unsafe_allow_html=True)
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown(f"**Trạng thái:** {badge(status)}", unsafe_allow_html=True)
        with sc2:
            if overall:
                st.markdown(f"**Kết quả:** {badge(overall)}", unsafe_allow_html=True)
        with sc3:
            if pt:
                st.markdown(f"**Thời gian xử lý:** `{pt:.1f}s`")

        # ── Missing docs panel ─────────────────────────────────────────────────
        if missing_files_to_reupload or summary.get("missing", 0) > 0:
            files_data = api_get(f"/files/{session_id}")
            uploaded_types = []
            if files_data:
                uploaded_types = [f.get("doc_type", "") for f in files_data.get("files", [])]
            render_missing_docs_panel(results_by_domain, uploaded_types,
                                      missing_files_to_reupload=missing_files_to_reupload)

        # ── Validation detail table ────────────────────────────────────────────
        if results_by_domain:
            st.markdown("### 📋 Chi Tiết Xác Minh")

            domain_icons = {
                "borrower": "👤 Borrower Agent", "assets": "🏦 Asset Agent",
                "employment": "💼 Employment Agent", "real_estate_owned": "🏠 REO Agent",
            }

            # Filter controls
            filter_col1, filter_col2 = st.columns([2, 4])
            with filter_col1:
                show_status = st.multiselect(
                    "Lọc theo trạng thái",
                    ["PASS", "FAIL", "MISSING"],
                    default=["PASS", "FAIL", "MISSING"],
                    key="status_filter",
                )

            for domain, findings in results_by_domain.items():
                filtered = [f for f in findings if f.get("status", "").upper() in show_status]
                if not filtered:
                    continue

                label = domain_icons.get(domain, f"📋 {domain.upper()}")
                pass_cnt    = sum(1 for f in filtered if f.get("status") == "PASS")
                fail_cnt    = sum(1 for f in filtered if f.get("status") == "FAIL")
                missing_cnt = sum(1 for f in filtered if f.get("status") == "MISSING")

                header = (
                    f"{label} &nbsp; "
                    f"<span style='color:#3fb950'>✅{pass_cnt}</span> &nbsp;"
                    f"<span style='color:#f85149'>❌{fail_cnt}</span> &nbsp;"
                    f"<span style='color:#d29922'>⚠️{missing_cnt}</span>"
                )

                with st.expander(f"{label} ({len(filtered)} mục)", expanded=True):
                    # Header row
                    hc1, hc2, hc3, hc4 = st.columns([4, 3, 3, 1])
                    hc1.markdown("**Trường**")
                    hc2.markdown("**Kỳ vọng (XML)**")
                    hc3.markdown("**Tìm thấy (PDF)**")
                    hc4.markdown("**Kết quả**")
                    st.markdown("<hr style='margin:4px 0;border-color:#30363d'>", unsafe_allow_html=True)

                    for f in filtered:
                        fc1, fc2, fc3, fc4 = st.columns([4, 3, 3, 1])
                        st_val = f.get("status", "MISSING").upper()

                        with fc1:
                            st.markdown(f"`{f['field_name']}`")

                        with fc2:
                            exp = f.get("expected_value") or "—"
                            color = "#8b949e" if exp == "—" else "#e6edf3"
                            st.markdown(
                                f"<span style='color:{color};font-family:monospace;font-size:0.82rem'>{exp}</span>",
                                unsafe_allow_html=True,
                            )

                        with fc3:
                            found = f.get("extracted_value")
                            if st_val == "MISSING" or found is None:
                                # Hiển thị badge MISSING thay vì "Không tìm thấy"
                                st.markdown(
                                    '<span class="status-badge badge-missing">⚠️ MISSING</span>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                color = "#3fb950" if st_val == "PASS" else "#f85149"
                                st.markdown(
                                    f"<span style='color:{color};font-family:monospace;font-size:0.82rem'>{found}</span>",
                                    unsafe_allow_html=True,
                                )

                        with fc4:
                            st.markdown(badge(st_val), unsafe_allow_html=True)

        elif status == "PROCESSING":
            st.info("⏳ Đang xử lý — nhấn 🔄 Refresh để cập nhật.")
        elif status in ("CREATED",):
            st.info("Chưa bắt đầu xử lý. Vào tab **📤 Upload** để chạy.")
        else:
            st.info("Chưa có kết quả xác minh.")


# ── Page: Agent Logs ───────────────────────────────────────────────────────────
elif page == "📋 Agent Logs":
    st.markdown("## 📋 Nhật Ký Xử Lý")

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("last_session_id", ""),
        placeholder="Session ID",
    )

    if session_id:
        data = api_get(f"/logs/{session_id}")
        if data:
            logs = data.get("logs", [])
            if logs:
                level_filter = st.multiselect(
                    "Lọc theo mức độ", ["INFO", "WARNING", "ERROR"],
                    default=["INFO", "WARNING", "ERROR"]
                )
                for log in reversed(logs):
                    if log["level"] not in level_filter:
                        continue
                    lvl_cls = {"INFO": "log-info", "WARNING": "log-warning", "ERROR": "log-error"}.get(log["level"], "log-info")
                    ts = log["created_at"][:19].replace("T", " ")
                    st.markdown(
                        f'<div class="log-entry {lvl_cls}">'
                        f'[{ts}] [{log["level"]:8s}] [{log["agent_name"]:20s}] {log["message"]}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("Chưa có log. Hãy chạy xử lý trước.")


# ── Page: Chunk Preview ────────────────────────────────────────────────────────
elif page == "🔍 Chunk Preview":
    st.markdown("## 🔍 Xem Trước Document Chunks")
    st.caption("Xem cách tài liệu được chia nhỏ trước khi đưa vào AI phân tích.")

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("last_session_id", ""),
        placeholder="Session ID",
    )
    domain_filter = st.selectbox("Lọc theo domain", ["all", "borrower", "asset", "employment", "reo"])

    if session_id:
        url = f"/chunks/{session_id}" + (f"?domain={domain_filter}" if domain_filter != "all" else "")
        data = api_get(url)
        if data:
            chunks = data.get("chunks", [])
            st.markdown(f"**{data.get('total_returned', 0)} chunks**")
            for c in chunks:
                st.markdown(f"""<div class="chunk-card">
<b>[Chunk {c['chunk_index']}]</b> &nbsp; {c['source_file']} &nbsp;|&nbsp;
trang {c['page_number']} &nbsp;|&nbsp; domain: <b>{c.get('domain','?')}</b> &nbsp;|&nbsp;
{c.get('token_count',0)} tokens
<hr style="border-color:#30363d;margin:6px 0">
{c['text_preview']}
</div>""", unsafe_allow_html=True)


# ── Page: Session History ──────────────────────────────────────────────────────
elif page == "📅 Session History":
    st.markdown("## 📅 Lịch Sử Session")

    if st.button("🔄 Refresh danh sách"):
        st.rerun()

    data = api_get("/sessions")
    if data:
        sessions = data.get("sessions", [])
        if sessions:
            for s in sessions:
                c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 2, 1, 1, 1])
                with c1:
                    st.code(s["session_id"][:20] + "...", language=None)
                with c2:
                    st.markdown(badge(s["status"]), unsafe_allow_html=True)
                with c3:
                    if s.get("overall_status"):
                        st.markdown(badge(s["overall_status"]), unsafe_allow_html=True)
                with c4:
                    st.markdown(f"{s.get('pdf_count',0)} PDFs")
                with c5:
                    if s.get("processing_time_sec"):
                        st.markdown(f"`{s['processing_time_sec']:.1f}s`")
                with c6:
                    if st.button("Xem", key=f"load_{s['session_id']}"):
                        st.session_state["last_session_id"] = s["session_id"]
                        st.success("Đã load session!")
                st.divider()
        else:
            st.info("Chưa có session nào. Upload tài liệu để bắt đầu.")
