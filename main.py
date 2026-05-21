import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
from datetime import datetime
import os
import requests
from urllib.parse import urlencode
from openai import OpenAI  # xAI uses an OpenAI-compatible SDK

st.set_page_config(page_title="Advisory Health Check", layout="wide")

# ======================= THEME =======================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');

    html, body, .stApp, .main { background: #0A1628 !important; color: #CBD5E1; font-family: 'DM Sans', sans-serif; }
    h1 { font-family: 'DM Serif Display', serif; color: #E2F0FF; font-size: 2.2rem; letter-spacing: -0.5px; }
    h2, h3 { font-family: 'DM Serif Display', serif; color: #CBD5E1; }
    .stMetric { background: #111D35; padding: 1.2rem; border-radius: 14px; border: 1px solid #1E3A5F; }
    .stMetric label { color: #64748B !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; }
    .stMetric [data-testid="metric-container"] > div:nth-child(2) { color: #E2F0FF !important; font-size: 1.6rem; font-weight: 600; }
    .stButton > button { background: #1565C0; color: white; border: none; border-radius: 8px; font-weight: 500; padding: 0.5rem 1.2rem; transition: background 0.2s; }
    .stButton > button:hover { background: #1976D2; }
    .stSelectbox label, .stTextInput label, .stTextArea label { color: #94A3B8 !important; font-size: 0.82rem; }
    .stSelectbox > div > div, .stTextInput > div > div > input, .stTextArea textarea { background: #111D35 !important; color: #CBD5E1 !important; border: 1px solid #1E3A5F !important; border-radius: 8px !important; }
    .stSidebar { background: #070F1E !important; border-right: 1px solid #1E3A5F; }
    .stSidebar h1, .stSidebar h2, .stSidebar h3 { color: #E2F0FF; }
    .stDivider { border-color: #1E3A5F !important; }
    .stExpander { background: #111D35 !important; border: 1px solid #1E3A5F !important; border-radius: 10px; }
    .stChatMessage { background: #111D35 !important; border: 1px solid #1E3A5F !important; border-radius: 12px; margin-bottom: 0.5rem; }
    .stChatInputContainer { background: #111D35 !important; border: 1px solid #1E3A5F !important; border-radius: 12px; }
    div[data-testid="stChatInput"] textarea { background: #111D35 !important; color: #CBD5E1 !important; }

    .health-badge { display: inline-block; padding: 0.3rem 1rem; border-radius: 999px; font-size: 0.85rem; font-weight: 600; letter-spacing: 0.04em; }
    .badge-green { background: #064E3B; color: #6EE7B7; border: 1px solid #065F46; }
    .badge-yellow { background: #78350F; color: #FCD34D; border: 1px solid #92400E; }
    .badge-red { background: #7F1D1D; color: #FCA5A5; border: 1px solid #991B1B; }

    .section-card { background: #111D35; border: 1px solid #1E3A5F; border-radius: 14px; padding: 1.4rem 1.6rem; margin-bottom: 1rem; }
    .flag-item { padding: 0.5rem 0.8rem; border-radius: 8px; margin: 0.3rem 0; font-size: 0.88rem; }
    .flag-red { background: #450A0A; border-left: 3px solid #EF4444; color: #FCA5A5; }
    .flag-yellow { background: #451A03; border-left: 3px solid #F59E0B; color: #FDE68A; }
    .flag-green { background: #052E16; border-left: 3px solid #22C55E; color: #86EFAC; }
    </style>
""", unsafe_allow_html=True)

# ======================= CONFIG =======================
# ⚠️ REDIRECT_URI must exactly match what is registered in your Xero Developer Portal
REDIRECT_URI = "https://advisory-health-check.onrender.com"

XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
XAI_API_KEY = os.getenv("XAI_API_KEY")

# ======================= SESSION STATE =======================
for key, default in {
    "xero_token": None,
    "xero_exchange_attempted": False,
    "selected_tenant": None,
    "tenant_list": [],
    "bs_data": None,
    "pl_data": None,
    "analysis": None,
    "chat_history": [],
    "chat_started": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================= HELPERS =======================

def format_currency(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:,.0f}"

def extract_xero_value(report_data, section_name, row_name=None):
    try:
        reports = report_data.get("Reports", [])
        if not reports:
            return None
        rows = reports[0].get("Rows", [])
        for section in rows:
            title = section.get("Title", "")
            if section_name.lower() in title.lower():
                section_rows = section.get("Rows", [])
                for row in section_rows:
                    cells = row.get("Cells", [])
                    if row_name:
                        if cells and row_name.lower() in cells[0].get("Value", "").lower():
                            try:
                                return float(cells[1].get("Value", "0").replace(",", "") or 0)
                            except:
                                return None
                    else:
                        if cells and len(cells) > 1:
                            try:
                                return float(cells[1].get("Value", "0").replace(",", "") or 0)
                            except:
                                return None
        return None
    except:
        return None

def extract_all_values(report_data, section_name):
    result = {}
    try:
        reports = report_data.get("Reports", [])
        if not reports:
            return result
        rows = reports[0].get("Rows", [])
        for section in rows:
            title = section.get("Title", "")
            if section_name.lower() in title.lower():
                for row in section.get("Rows", []):
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        label = cells[0].get("Value", "").strip()
                        try:
                            val = float(cells[1].get("Value", "0").replace(",", "") or 0)
                        except:
                            val = 0
                        if label:
                            result[label] = val
    except:
        pass
    return result

def parse_financials(bs_data, pl_data):
    fin = {}

    fin["current_assets"] = extract_xero_value(bs_data, "Current Assets")
    fin["total_assets"] = extract_xero_value(bs_data, "Total Assets")
    fin["current_liabilities"] = extract_xero_value(bs_data, "Current Liabilities")
    fin["total_liabilities"] = extract_xero_value(bs_data, "Total Liabilities")
    fin["equity"] = extract_xero_value(bs_data, "Total Equity")

    if fin["current_assets"] is None:
        fin["current_assets"] = extract_xero_value(bs_data, "current")
    if fin["total_liabilities"] is None:
        fin["total_liabilities"] = extract_xero_value(bs_data, "liabilities")

    fin["revenue"] = extract_xero_value(pl_data, "Income")
    if fin["revenue"] is None:
        fin["revenue"] = extract_xero_value(pl_data, "Revenue")
    fin["gross_profit"] = extract_xero_value(pl_data, "Gross Profit")
    fin["net_profit"] = extract_xero_value(pl_data, "Net Profit")
    if fin["net_profit"] is None:
        fin["net_profit"] = extract_xero_value(pl_data, "Profit")
    fin["expenses"] = extract_xero_value(pl_data, "Expenses")
    if fin["expenses"] is None:
        fin["expenses"] = extract_xero_value(pl_data, "Total Expenses")

    ca = fin["current_assets"] or 0
    cl = fin["current_liabilities"] or 0
    ta = fin["total_assets"] or 0
    tl = fin["total_liabilities"] or 0
    rev = fin["revenue"] or 1
    np_ = fin["net_profit"] or 0
    eq = fin["equity"] or 0

    fin["current_ratio"] = round(ca / cl, 2) if cl else None
    fin["debt_to_equity"] = round(tl / eq, 2) if eq else None
    fin["net_profit_margin"] = round((np_ / rev) * 100, 1) if rev else None
    fin["working_capital"] = ca - cl
    fin["solvency_ratio"] = round(eq / ta, 2) if ta else None

    return fin

def assess_health(fin):
    flags = []
    score = 100

    cr = fin.get("current_ratio")
    if cr is not None:
        if cr < 1.0:
            flags.append(("red", f"⚠️ Current ratio is {cr:.2f} — liabilities exceed current assets. The business may struggle to meet short-term obligations."))
            score -= 25
        elif cr < 1.5:
            flags.append(("yellow", f"Current ratio is {cr:.2f} — acceptable but tight. Monitor closely."))
            score -= 10
        else:
            flags.append(("green", f"Current ratio is {cr:.2f} — healthy liquidity position."))

    wc = fin.get("working_capital")
    if wc is not None and wc < 0:
        flags.append(("red", f"⚠️ Negative working capital (${wc:,.0f}) — the business owes more in the short term than it currently holds in liquid assets."))
        score -= 20

    npm = fin.get("net_profit_margin")
    if npm is not None:
        if npm < 0:
            flags.append(("red", f"⚠️ Net profit margin is {npm:.1f}% — the business is operating at a loss."))
            score -= 25
        elif npm < 5:
            flags.append(("yellow", f"Net profit margin is {npm:.1f}% — very thin. Small cost increases could push into loss territory."))
            score -= 10
        else:
            flags.append(("green", f"Net profit margin is {npm:.1f}% — profitable operations."))

    dte = fin.get("debt_to_equity")
    if dte is not None:
        if dte > 3:
            flags.append(("red", f"⚠️ Debt-to-equity ratio is {dte:.2f} — highly leveraged. Creditors have significant claims over the business."))
            score -= 20
        elif dte > 2:
            flags.append(("yellow", f"Debt-to-equity ratio is {dte:.2f} — elevated leverage. Worth reviewing debt servicing capacity."))
            score -= 10
        else:
            flags.append(("green", f"Debt-to-equity ratio is {dte:.2f} — manageable leverage."))

    eq = fin.get("equity")
    if eq is not None and eq < 0:
        flags.append(("red", "🚨 Negative equity — total liabilities exceed total assets. This is a critical insolvency warning sign. Directors should seek immediate professional advice."))
        score -= 30

    sr = fin.get("solvency_ratio")
    if sr is not None:
        if sr < 0.2:
            flags.append(("red", f"⚠️ Solvency ratio is {sr:.2f} — only {sr*100:.0f}% of assets are funded by equity. Very low buffer against insolvency."))
            score -= 15
        elif sr < 0.4:
            flags.append(("yellow", f"Solvency ratio is {sr:.2f} — moderate. Consider whether debt levels are sustainable given revenue trends."))
            score -= 5

    score = max(0, score)
    if score >= 70:
        rating, label = "green", "HEALTHY"
    elif score >= 45:
        rating, label = "yellow", "CAUTION"
    else:
        rating, label = "red", "AT RISK"

    return flags, score, rating, label

def build_ai_prompt(fin, flags, company_name, industry, business_type, extra_context):
    flag_text = "\n".join([f"- [{f[0].upper()}] {f[1]}" for f in flags])
    return f"""You are a senior Australian financial advisor and registered liquidator speaking directly to the director of a small business. Your tone is warm, clear, and plain-English — no jargon. You genuinely care about helping them understand their situation.

COMPANY: {company_name}
INDUSTRY: {industry}
BUSINESS TYPE: {business_type}
EXTRA CONTEXT: {extra_context or 'None provided'}

FINANCIAL SUMMARY:
- Revenue: {format_currency(fin.get('revenue'))}
- Net Profit: {format_currency(fin.get('net_profit'))} ({fin.get('net_profit_margin', 'N/A')}% margin)
- Current Assets: {format_currency(fin.get('current_assets'))}
- Current Liabilities: {format_currency(fin.get('current_liabilities'))}
- Total Assets: {format_currency(fin.get('total_assets'))}
- Total Liabilities: {format_currency(fin.get('total_liabilities'))}
- Equity: {format_currency(fin.get('equity'))}
- Working Capital: {format_currency(fin.get('working_capital'))}
- Current Ratio: {fin.get('current_ratio', 'N/A')}
- Debt-to-Equity: {fin.get('debt_to_equity', 'N/A')}
- Solvency Ratio: {fin.get('solvency_ratio', 'N/A')}

FLAGS IDENTIFIED:
{flag_text}

INSTRUCTIONS:
1. Open with a brief, plain-English summary of what the numbers tell you — what is going well and what needs attention.
2. Address the most important solvency and liquidity items directly. If there are red flags, be honest but constructive.
3. Give 2–3 practical, actionable next steps the director can take.
4. If there are any red or yellow flags, recommend they speak with their accountant or a registered liquidator.
5. Close by asking the director what specific area they'd like to explore further.
Keep your response to under 350 words. Use plain paragraphs, no bullet points in your opening response."""

def get_ai_response(messages, system_prompt):
    if not XAI_API_KEY:
        return "⚠️ xAI API key not configured. Set XAI_API_KEY in your Render environment variables to enable AI chat."
    try:
        client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = client.chat.completions.create(
            model="grok-3",
            messages=full_messages,
            max_tokens=600,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ AI error: {str(e)}"

# ======================= ENV CHECK =======================
if not XERO_CLIENT_ID or not XERO_CLIENT_SECRET:
    st.warning("⚠️ Xero credentials missing. Set XERO_CLIENT_ID and XERO_CLIENT_SECRET in Render environment variables.")

# ======================= HEADER =======================
st.title("🧠 Advisory Health Check")
st.markdown("**Financial Health & Insolvency Early Warning — for Business Directors**")
st.error("⚠️ SCREENING TOOL ONLY — Not professional advice. Always consult a qualified accountant or registered liquidator.")

# ======================= SIDEBAR =======================
with st.sidebar:
    st.header("Client Profile")
    company_name = st.text_input("Company / Client Name", "Client Business Pty Ltd")
    business_type = st.selectbox("Business Type",
        ["Established Small Business", "Startup with Recent Funding", "High-Growth Company", "Family Business", "Other"])
    industry = st.selectbox("Industry", [
        "General / Multi-Industry", "Retail & E-commerce", "Construction & Trades",
        "Professional Services (Accounting, Legal, etc.)", "Manufacturing", "Hospitality & Food Services",
        "IT & Digital Services", "Health & Aged Care", "Transport & Logistics",
        "Agriculture & Farming", "Wholesale & Distribution", "Real Estate & Property Services"
    ])
    extra_context = st.text_area("Extra Context", placeholder="Recent investment, major contract, ATO debt...", height=100)

    st.divider()
    st.subheader("🔗 Xero Integration")

    if st.session_state.xero_token:
        st.success("✅ Connected to Xero")
        if st.button("Disconnect Xero", use_container_width=True):
            for key in ["xero_token", "xero_exchange_attempted", "selected_tenant",
                        "tenant_list", "bs_data", "pl_data", "analysis", "chat_history", "chat_started"]:
                st.session_state[key] = None if key in ["xero_token", "selected_tenant", "bs_data", "pl_data", "analysis"] else [] if key in ["tenant_list", "chat_history"] else False
            st.query_params.clear()
            st.rerun()
    else:
        if st.button("Connect to Xero", use_container_width=True):
            if not XERO_CLIENT_ID:
                st.error("XERO_CLIENT_ID not set.")
            else:
                params = {
                    "response_type": "code",
                    "client_id": XERO_CLIENT_ID,
                    "redirect_uri": REDIRECT_URI,
                    "scope": "accounting.reports.read accounting.settings.read offline_access",
                    "state": "xero123",
                }
                auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
                st.markdown(f"[🔐 Click here to authorise with Xero]({auth_url})")
                st.caption("You will be redirected back after authorising.")

# ======================= XERO OAUTH CALLBACK =======================
query_params = st.query_params

if (
    "code" in query_params
    and not st.session_state.xero_exchange_attempted
    and st.session_state.xero_token is None
):
    st.session_state.xero_exchange_attempted = True

    if query_params.get("state", "") != "xero123":
        st.error("❌ State mismatch. Please try connecting again.")
        st.query_params.clear()
        st.stop()

    with st.spinner("Exchanging authorisation code with Xero..."):
        try:
            resp = requests.post(
                "https://identity.xero.com/connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": query_params["code"],
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(XERO_CLIENT_ID, XERO_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if resp.ok:
                st.session_state.xero_token = resp.json()
                st.query_params.clear()
                st.rerun()
            else:
                st.session_state.xero_exchange_attempted = False
                st.error(f"❌ Token exchange failed: {resp.text}")
                st.query_params.clear()
        except Exception as e:
            st.session_state.xero_exchange_attempted = False
            st.error(f"❌ Error: {str(e)}")
            st.query_params.clear()

# ======================= TENANT SELECTION =======================
if st.session_state.xero_token and not st.session_state.selected_tenant:
    with st.spinner("Loading your Xero organisations..."):
        try:
            access_token = st.session_state.xero_token["access_token"]
            conn_resp = requests.get(
                "https://api.xero.com/connections",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=15,
            )
            if conn_resp.ok:
                tenants = conn_resp.json()
                st.session_state.tenant_list = tenants
            else:
                st.error(f"Could not load Xero organisations: {conn_resp.text}")
                tenants = []
        except Exception as e:
            st.error(f"Error loading organisations: {e}")
            tenants = []

    if len(tenants) == 0:
        st.warning("No Xero organisations found on this account.")
    elif len(tenants) == 1:
        st.session_state.selected_tenant = tenants[0]
        st.rerun()
    else:
        st.subheader("🏢 Select Xero Organisation")
        st.markdown("Multiple Xero connections found. Please choose which one to analyse:")
        for t in tenants:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{t.get('tenantName', 'Unknown')}**  \n`{t.get('tenantType', '')}` · ID: `{t.get('tenantId', '')[:8]}...`")
            with col2:
                if st.button("Select", key=t["tenantId"]):
                    st.session_state.selected_tenant = t
                    st.rerun()
        st.stop()

# ======================= FETCH DATA BUTTON =======================
if st.session_state.selected_tenant and st.session_state.bs_data is None:
    tenant = st.session_state.selected_tenant
    st.info(f"Connected to: **{tenant.get('tenantName', 'Your Organisation')}**")

    if st.button("📥 Fetch & Analyse Financial Data", type="primary"):
        with st.spinner("Fetching reports from Xero..."):
            try:
                access_token = st.session_state.xero_token["access_token"]
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Xero-Tenant-Id": tenant["tenantId"],
                    "Accept": "application/json",
                }
                params = {"periods": 6, "timeframe": "MONTH"}
                bs_resp = requests.get("https://api.xero.com/api.xro/2.0/Reports/BalanceSheet", headers=headers, params=params, timeout=15)
                pl_resp = requests.get("https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss", headers=headers, params=params, timeout=15)

                if bs_resp.ok and pl_resp.ok:
                    st.session_state.bs_data = bs_resp.json()
                    st.session_state.pl_data = pl_resp.json()
                    st.rerun()
                else:
                    st.error(f"Balance Sheet: {bs_resp.status_code} — {bs_resp.text[:300]}")
                    st.error(f"P&L: {pl_resp.status_code} — {pl_resp.text[:300]}")
            except Exception as e:
                st.error(f"Error: {e}")

# ======================= ANALYSIS DASHBOARD =======================
if st.session_state.bs_data and st.session_state.pl_data:

    fin = parse_financials(st.session_state.bs_data, st.session_state.pl_data)
    flags, score, rating, label = assess_health(fin)

    badge_class = f"badge-{rating}"

    st.markdown("---")
    col_title, col_badge = st.columns([5, 1])
    with col_title:
        st.markdown(f"## Financial Health Report — {company_name}")
        st.caption(f"Data from Xero · {st.session_state.selected_tenant.get('tenantName', '')} · Generated {datetime.now().strftime('%d %b %Y')}")
    with col_badge:
        st.markdown(f"<div style='margin-top:1.5rem'><span class='health-badge {badge_class}'>{label}</span><br><span style='color:#64748B;font-size:0.75rem'>Score: {score}/100</span></div>", unsafe_allow_html=True)

    st.markdown("### Key Metrics")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Revenue", format_currency(fin["revenue"]))
    m2.metric("Net Profit", format_currency(fin["net_profit"]), f"{fin['net_profit_margin']}%" if fin['net_profit_margin'] else None)
    m3.metric("Current Assets", format_currency(fin["current_assets"]))
    m4.metric("Current Liabilities", format_currency(fin["current_liabilities"]))
    m5.metric("Total Equity", format_currency(fin["equity"]))
    m6.metric("Working Capital", format_currency(fin["working_capital"]))

    st.markdown("### Solvency & Liquidity Ratios")
    r1, r2, r3 = st.columns(3)

    cr = fin.get("current_ratio")
    cr_delta = "✅ Good" if cr and cr >= 1.5 else ("⚠️ Watch" if cr and cr >= 1.0 else "🚨 Critical")
    r1.metric("Current Ratio", f"{cr:.2f}" if cr else "N/A", cr_delta, delta_color="off")

    dte = fin.get("debt_to_equity")
    dte_delta = "✅ Low" if dte and dte <= 1 else ("⚠️ Moderate" if dte and dte <= 2 else "🚨 High")
    r2.metric("Debt-to-Equity", f"{dte:.2f}" if dte else "N/A", dte_delta, delta_color="off")

    sr = fin.get("solvency_ratio")
    sr_delta = "✅ Solid" if sr and sr >= 0.4 else ("⚠️ Low" if sr and sr >= 0.2 else "🚨 Very Low")
    r3.metric("Solvency Ratio", f"{sr:.2f}" if sr else "N/A", sr_delta, delta_color="off")

    st.markdown("### Financial Position")
    ch1, ch2 = st.columns(2)

    with ch1:
        assets = fin["current_assets"] or 0
        liabilities = fin["current_liabilities"] or 0
        equity = fin["equity"] or 0
        fig = go.Figure(go.Bar(
            x=["Current Assets", "Current Liabilities", "Equity"],
            y=[assets, liabilities, equity],
            marker_color=["#22C55E", "#EF4444", "#3B82F6"],
            text=[format_currency(assets), format_currency(liabilities), format_currency(equity)],
            textposition="outside",
        ))
        fig.update_layout(
            title="Balance Sheet Snapshot",
            paper_bgcolor="#111D35", plot_bgcolor="#111D35",
            font=dict(color="#CBD5E1", family="DM Sans"),
            showlegend=False, height=320,
            yaxis=dict(gridcolor="#1E3A5F"),
            margin=dict(t=40, b=20, l=10, r=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        rev = fin["revenue"] or 0
        exp = fin["expenses"] or 0
        np_ = fin["net_profit"] or 0
        fig2 = go.Figure(go.Bar(
            x=["Revenue", "Expenses", "Net Profit"],
            y=[rev, exp, np_],
            marker_color=["#3B82F6", "#F59E0B", "#22C55E" if np_ >= 0 else "#EF4444"],
            text=[format_currency(rev), format_currency(exp), format_currency(np_)],
            textposition="outside",
        ))
        fig2.update_layout(
            title="Profit & Loss Snapshot",
            paper_bgcolor="#111D35", plot_bgcolor="#111D35",
            font=dict(color="#CBD5E1", family="DM Sans"),
            showlegend=False, height=320,
            yaxis=dict(gridcolor="#1E3A5F"),
            margin=dict(t=40, b=20, l=10, r=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### Health Assessment")
    for severity, message in flags:
        css_class = f"flag-{severity}"
        st.markdown(f"<div class='flag-item {css_class}'>{message}</div>", unsafe_allow_html=True)

    any_concern = any(s in ["red", "yellow"] for s, _ in flags)
    if any_concern:
        st.markdown("""
        <div style='margin-top:1rem; padding:0.9rem 1.2rem; background:#0C1F3F; border:1px solid #1D4ED8;
             border-radius:10px; color:#93C5FD; font-size:0.88rem;'>
        💼 <strong>Recommendation:</strong> One or more areas require attention. We strongly recommend
        speaking with your accountant or a registered liquidator before making major financial decisions.
        </div>
        """, unsafe_allow_html=True)

    with st.expander("🔍 Raw Xero JSON (debug)"):
        st.json(st.session_state.bs_data)
        st.json(st.session_state.pl_data)

    # ======================= AI CHAT =======================
    st.markdown("---")
    st.markdown("### 💬 Your Financial Advisor")

    system_prompt = build_ai_prompt(fin, flags, company_name, industry, business_type, extra_context)
    system_prompt += "\n\nIn all follow-up messages: be conversational, plain-English, and no longer than necessary. If the user's question touches on serious solvency concerns, always recommend they speak with their accountant or a registered liquidator."

    if not st.session_state.chat_started:
        with st.spinner("Your advisor is reviewing the numbers..."):
            opening = get_ai_response([], system_prompt)
            st.session_state.chat_history.append({"role": "assistant", "content": opening})
            st.session_state.chat_started = True

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask about your financials, cash flow, solvency, or next steps...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = get_ai_response(st.session_state.chat_history, system_prompt)
                st.markdown(reply)
        st.session_state.chat_history.append({"role": "assistant", "content": reply})

# ======================= CSV FALLBACK =======================
if not st.session_state.bs_data:
    st.markdown("---")
    st.subheader("📂 Manual Upload (CSV Fallback)")
    uploaded_file = st.file_uploader("Upload a CSV export as fallback if not using Xero", type=["csv"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.success("✅ CSV loaded")
        st.dataframe(df.head(20))

st.caption("Advisory Health Check • Built for Australian Business Directors")
