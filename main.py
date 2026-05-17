import streamlit as st
import pandas as pd
import plotly.express as px
from fpdf import FPDF
from datetime import datetime
import os
import requests
from openai import OpenAI

st.set_page_config(page_title="Advisory Health Check", layout="wide")

# Professional Dark Theme
st.markdown("""
    <style>
    .main {background: #0F1626; color: #E0F2FF;}
    .stApp {background: #0F1626;}
    .stMetric {background: #1A2338; padding: 1rem; border-radius: 12px; border: 1px solid #00D4FF33;}
    h1, h2 {color: #00D4FF;}
    </style>
""", unsafe_allow_html=True)

st.title("🧠 Advisory Health Check")
st.markdown("**Professional Financial Health & Insolvency Early Warning Tool**")

st.error("⚠️ SCREENING TOOL ONLY — Not professional advice. Always consult a qualified accountant or registered liquidator.")

# ======================= SECRETS (Render compatible) =======================
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = "https://advisory-health-check.onrender.com"   # ← Your Render URL

# ======================= SESSION STATE =======================
if "xero_token" not in st.session_state:
    st.session_state.xero_token = None
if "xero_data_df" not in st.session_state:
    st.session_state.xero_data_df = None

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

    extra_context = st.text_area("Extra Context", placeholder="Recent investment, major contract...", height=100)

    st.divider()
    st.subheader("🔗 Xero Integration")
    if st.button("Connect to Xero", use_container_width=True):
        scope = "accounting.reports.balancesheet.read accounting.reports.profitandloss.read accounting.settings.read offline_access"
        auth_url = (
            f"https://login.xero.com/identity/connect/authorize?"
            f"response_type=code&client_id={XERO_CLIENT_ID}&redirect_uri={REDIRECT_URI}"
            f"&scope={scope.replace(' ', '%20')}&state=xero123"
        )
        st.markdown(f"[🔐 Connect to Xero]({auth_url})", unsafe_allow_html=True)

# ======================= HANDLE OAUTH CALLBACK =======================
query_params = st.query_params
if "code" in query_params and st.session_state.xero_token is None:
    with st.spinner("Connecting to Xero..."):
        code = query_params["code"]
        token_url = "https://identity.xero.com/connect/token"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI
        }
        resp = requests.post(token_url, data=data, auth=(XERO_CLIENT_ID, XERO_CLIENT_SECRET))
        
        if resp.ok:
            st.session_state.xero_token = resp.json()
            st.success("🎉 Successfully connected to Xero!")
            st.rerun()
        else:
            st.error(f"Token exchange failed: {resp.text}")

# ======================= PULL XERO DATA =======================
if st.session_state.get("xero_token"):
    if st.button("📥 Pull Latest Data from Xero"):
        try:
            headers = {
                "Authorization": f"Bearer {st.session_state.xero_token['access_token']}",
                "Xero-Tenant-Id": ""  # Will be filled
            }
            # Get Tenant
            tenants = requests.get("https://api.xero.com/connections", headers=headers).json()
            if tenants:
                tenant_id = tenants[0]["tenantId"]
                headers["Xero-Tenant-Id"] = tenant_id

                bs_resp = requests.get("https://api.xero.com/api.xro/2.0/Reports/BalanceSheet?periods=6", headers=headers)
                if bs_resp.ok:
                    st.success("✅ Data pulled from Xero!")
                    # TODO: Parse into df (we'll do this next)
                else:
                    st.error("Failed to fetch reports")
        except Exception as e:
            st.error(f"Error: {e}")

# ======================= CSV FALLBACK =======================
uploaded_file = st.file_uploader("Or upload CSV as fallback", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    # ... (your existing calculations, metrics, charts, AI chat)

st.caption("Advisory Health Check • Live on Render")
