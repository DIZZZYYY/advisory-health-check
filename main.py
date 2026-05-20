import streamlit as st
import pandas as pd
import plotly.express as px
from fpdf import FPDF
from datetime import datetime
import os
import requests
from urllib.parse import urlencode
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

# ======================= CONFIG =======================
REDIRECT_URI = "https://advisory-health-check-1.onrender.com"  # Must match Xero Developer Portal exactly

XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")

# ======================= ENV VAR VALIDATION =======================
if not XERO_CLIENT_ID or not XERO_CLIENT_SECRET:
    st.warning("⚠️ Xero credentials not found in environment variables. Xero integration will not work until XERO_CLIENT_ID and XERO_CLIENT_SECRET are set on Render.")

# ======================= SESSION STATE DEFAULTS =======================
if "xero_token" not in st.session_state:
    st.session_state.xero_token = None

if "xero_exchange_attempted" not in st.session_state:
    st.session_state.xero_exchange_attempted = False

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

    # Show connection status
    if st.session_state.xero_token:
        st.success("✅ Connected to Xero")
        if st.button("Disconnect Xero", use_container_width=True):
            st.session_state.xero_token = None
            st.session_state.xero_exchange_attempted = False
            st.query_params.clear()
            st.rerun()
    else:
        if st.button("Connect to Xero", use_container_width=True):
            if not XERO_CLIENT_ID:
                st.error("XERO_CLIENT_ID environment variable is not set.")
            else:
                scope = (
                    "accounting.reports.read "
                    "accounting.settings.read "
                    "offline_access"
                )
                params = {
                    "response_type": "code",
                    "client_id": XERO_CLIENT_ID,
                    "redirect_uri": REDIRECT_URI,
                    "scope": scope,
                    "state": "xero123",
                }
                auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
                st.markdown(f"[🔐 Click here to authorise with Xero]({auth_url})")
                st.caption("You will be redirected back here after authorising.")

# ======================= HANDLE XERO OAUTH CALLBACK =======================
query_params = st.query_params

# Only attempt token exchange once per callback — guards against Streamlit re-renders
# burning the single-use auth code
if (
    "code" in query_params
    and not st.session_state.xero_exchange_attempted
    and st.session_state.xero_token is None
):
    # Set flag IMMEDIATELY before any network call to prevent double-firing
    st.session_state.xero_exchange_attempted = True

    # Validate state parameter to guard against CSRF
    returned_state = query_params.get("state", "")
    if returned_state != "xero123":
        st.error("❌ State mismatch — possible CSRF issue. Please try connecting again.")
        st.query_params.clear()
        st.stop()

    with st.spinner("Exchanging authorisation code with Xero..."):
        code = query_params["code"]

        try:
            resp = requests.post(
                "https://identity.xero.com/connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(XERO_CLIENT_ID, XERO_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )

            if resp.ok:
                st.session_state.xero_token = resp.json()
                # Clear the code from the URL so it can never be re-attempted
                st.query_params.clear()
                st.success("🎉 Successfully connected to Xero!")
                st.rerun()
            else:
                # Reset flag so the user can try again
                st.session_state.xero_exchange_attempted = False
                st.error(f"❌ Token exchange failed: {resp.text}")
                st.info("Please try connecting to Xero again from the sidebar.")
                st.query_params.clear()

        except requests.exceptions.Timeout:
            st.session_state.xero_exchange_attempted = False
            st.error("❌ Request timed out connecting to Xero. Please try again.")
            st.query_params.clear()

        except Exception as e:
            st.session_state.xero_exchange_attempted = False
            st.error(f"❌ Unexpected error: {str(e)}")
            st.query_params.clear()

# ======================= FETCH XERO DATA =======================
if st.session_state.get("xero_token"):
    if st.button("📥 Fetch Xero Data"):
        with st.spinner("Fetching data from Xero..."):
            try:
                access_token = st.session_state.xero_token["access_token"]

                # Step 1: Get tenant list (do NOT include Xero-Tenant-Id here)
                connections_resp = requests.get(
                    "https://api.xero.com/connections",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                    timeout=15,
                )

                if not connections_resp.ok or not connections_resp.json():
                    st.error(f"❌ Could not retrieve Xero organisation: {connections_resp.text}")
                    st.stop()

                tenant = connections_resp.json()[0]
                tenant_id = tenant["tenantId"]
                org_name = tenant.get("tenantName", "Your Organisation")
                st.success(f"Connected to: {org_name}")

                # Step 2: Build headers WITH tenant ID for report requests
                report_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Xero-Tenant-Id": tenant_id,
                    "Accept": "application/json",
                }

                params = {"periods": 6, "timeframe": "MONTH"}

                bs_resp = requests.get(
                    "https://api.xero.com/api.xro/2.0/Reports/BalanceSheet",
                    headers=report_headers,
                    params=params,
                    timeout=15,
                )
                pl_resp = requests.get(
                    "https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss",
                    headers=report_headers,
                    params=params,
                    timeout=15,
                )

                st.write("Balance Sheet Status:", bs_resp.status_code)
                st.write("P&L Status:", pl_resp.status_code)

                if bs_resp.ok and pl_resp.ok:
                    bs_data = bs_resp.json()
                    pl_data = pl_resp.json()
                    st.success("✅ Successfully received data from Xero!")

                    # Store in session state for use in metrics/charts below
                    st.session_state.bs_data = bs_data
                    st.session_state.pl_data = pl_data

                    # Debug view — remove once parsing is implemented
                    with st.expander("Raw Balance Sheet JSON (debug)"):
                        st.json(bs_data)
                    with st.expander("Raw P&L JSON (debug)"):
                        st.json(pl_data)
                else:
                    if not bs_resp.ok:
                        st.error(f"❌ Balance Sheet fetch failed: {bs_resp.text[:500]}")
                    if not pl_resp.ok:
                        st.error(f"❌ P&L fetch failed: {pl_resp.text[:500]}")

            except requests.exceptions.Timeout:
                st.error("❌ Request timed out fetching Xero reports. Please try again.")
            except Exception as e:
                st.error(f"❌ Error fetching Xero data: {str(e)}")

# ======================= CSV FALLBACK =======================
st.divider()
st.subheader("📂 Manual Data Upload")
uploaded_file = st.file_uploader("Upload CSV as fallback (if not using Xero)", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.success("✅ CSV data loaded successfully")
    st.dataframe(df.head(20))
    # Metrics, charts, AI analysis to be added here

st.caption("Advisory Health Check • Live on Render")
