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
    if st.button("📥 Fetch Xero Data"):
        with st.spinner("Fetching data from Xero..."):
            try:
                headers = {
                    "Authorization": f"Bearer {st.session_state.xero_token['access_token']}",
                    "Xero-Tenant-Id": ""
                }

                # Get Tenant ID
                st.info("📍 Step 1: Fetching tenant information...")
                tenants_resp = requests.get("https://api.xero.com/connections", headers=headers)
                
                if not tenants_resp.ok:
                    st.error(f"Failed to fetch tenants. Status: {tenants_resp.status_code}")
                    st.write("Response:", tenants_resp.text[:500])
                    st.stop()
                
                try:
                    tenants_data = tenants_resp.json()
                except:
                    st.error(f"Invalid JSON response from /connections. Response: {tenants_resp.text[:500]}")
                    st.stop()
                
                if not tenants_data:
                    st.error("No tenants found. Make sure your Xero account has data.")
                    st.stop()
                
                tenant = tenants_data[0]
                tenant_id = tenant.get("tenantId")
                headers["Xero-Tenant-Id"] = tenant_id
                st.success(f"✅ Connected to: {tenant.get('tenantName', 'Your Organisation')}")

                # Fetch Reports with better error handling
                st.info("📊 Step 2: Fetching Balance Sheet report...")
                bs_resp = requests.get(
                    "https://api.xero.com/api.xro/2.0/Reports/BalanceSheet?periods=6&timeframe=MONTH",
                    headers=headers
                )
                
                st.info("📈 Step 3: Fetching Profit & Loss report...")
                pl_resp = requests.get(
                    "https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss?periods=6&timeframe=MONTH",
                    headers=headers
                )

                # Debug: Show status codes and content
                st.write(f"**Balance Sheet Status:** {bs_resp.status_code}")
                st.write(f"**Balance Sheet Content Length:** {len(bs_resp.text)} chars")
                st.write(f"**P&L Status:** {pl_resp.status_code}")
                st.write(f"**P&L Content Length:** {len(pl_resp.text)} chars")

                # Check if responses are empty
                if not bs_resp.text.strip():
                    st.error("❌ **Balance Sheet API returned EMPTY response**")
                    st.write("**Headers sent:**", dict(headers))
                    st.warning("**Possible causes:**")
                    st.write("1. Your Xero account doesn't have any transactions/reports yet")
                    st.write("2. Your token doesn't have permission to access Balance Sheet")
                    st.write("3. The Xero API endpoint is temporarily down")
                    st.stop()
                
                if not pl_resp.text.strip():
                    st.error("❌ **P&L API returned EMPTY response**")
                    st.stop()

                # Show raw response (first 500 chars) for debugging
                st.info("📋 **Raw API Response (first 500 chars):**")
                st.code(bs_resp.text[:500], language="json")

                # Try to parse JSON
                try:
                    bs_data = bs_resp.json()
                except Exception as json_error:
                    st.error(f"❌ **Balance Sheet: Failed to parse JSON**")
                    st.write(f"Error: {str(json_error)}")
                    st.write(f"Raw response: {bs_resp.text[:1000]}")
                    st.stop()

                try:
                    pl_data = pl_resp.json()
                except Exception as json_error:
                    st.error(f"❌ **P&L: Failed to parse JSON**")
                    st.write(f"Error: {str(json_error)}")
                    st.stop()

                # Check for API error messages
                if isinstance(bs_data, dict) and "ApiException" in bs_resp.text:
                    st.error("❌ **Balance Sheet API Error**")
                    st.write("Response:", bs_data)
                    st.stop()

                if isinstance(pl_data, dict) and "ApiException" in pl_resp.text:
                    st.error("❌ **P&L API Error**")
                    st.write("Response:", pl_data)
                    st.stop()

                # Validate data structure
                if not isinstance(bs_data, dict) or "Reports" not in bs_data:
                    st.error("❌ **No 'Reports' key in Balance Sheet response**")
                    st.write("Available keys:", list(bs_data.keys()) if isinstance(bs_data, dict) else "Not a dict")
                    st.write("Full Response:", bs_data)
                    st.stop()

                if not bs_data["Reports"]:
                    st.error("❌ **'Reports' array is empty**")
                    st.write("Full Response:", bs_data)
                    st.stop()

                if "Reports" not in pl_data or not pl_data["Reports"]:
                    st.error("❌ **No P&L reports found in response**")
                    st.write("Available keys:", list(pl_data.keys()) if isinstance(pl_data, dict) else "Not a dict")
                    st.stop()

                bs_report = bs_data["Reports"][0]
                pl_report = pl_data["Reports"][0]

                st.success("✅ **Successfully parsed both reports!**")

                # Better parsing function
                def extract_value(report_rows, label):
                    for row in report_rows:
                        if row.get("RowType") == "Row":
                            cells = row.get("Cells", [])
                            if cells and label.lower() in cells[0].get("Value", "").lower():
                                try:
                                    return [float(c.get("Value", 0) or 0) for c in cells[1:]]
                                except (ValueError, TypeError):
                                    return [0.0] * len(cells[1:])
                    return [0.0] * 6

                # Extract period names
                if not bs_report.get("Rows"):
                    st.error("❌ **No rows found in Balance Sheet report**")
                    st.write("Report keys:", list(bs_report.keys()))
                    st.stop()

                header_row = bs_report["Rows"][0]
                period_names = [cell.get("Value", f"Period {i+1}") for i, cell in enumerate(header_row.get("Cells", [])[1:])]

                if not period_names:
                    st.error("❌ **Could not extract period names**")
                    st.stop()

                st.success(f"✅ Found {len(period_names)} periods: {', '.join(period_names[:3])}...")

                # Extract key values
                current_assets = extract_value(bs_report.get("Rows", []), "Total Current Assets")
                total_assets = extract_value(bs_report.get("Rows", []), "Total Assets")
                current_liab = extract_value(bs_report.get("Rows", []), "Total Current Liabilities")
                total_liab = extract_value(bs_report.get("Rows", []), "Total Liabilities")
                net_profit = extract_value(pl_report.get("Rows", []), "Net Profit")
                equity = extract_value(bs_report.get("Rows", []), "Total Equity")

                # Build DataFrame
                data_list = []
                for i in range(len(period_names)):
                    data_list.append({
                        "Period": period_names[i],
                        "Current_Assets": current_assets[i] if i < len(current_assets) else 0,
                        "Current_Liabilities": current_liab[i] if i < len(current_liab) else 0,
                        "Total_Assets": total_assets[i] if i < len(total_assets) else 0,
                        "Total_Liabilities": total_liab[i] if i < len(total_liab) else 0,
                        "Total_Equity": equity[i] if i < len(equity) else 0,
                        "Net_Profit": net_profit[i] if i < len(net_profit) else 0
                    })

                df = pd.DataFrame(data_list)
                st.session_state.xero_data_df = df
                st.success("✅ Successfully extracted data from Xero!")
                st.dataframe(df)

                # ======================= FINANCIAL METRICS =======================
                st.subheader("📊 Financial Health Metrics")
                
                # Calculate key ratios for the latest period (most recent)
                latest_idx = -1
                
                current_ratio = current_assets[latest_idx] / current_liab[latest_idx] if current_liab[latest_idx] > 0 else 0
                debt_to_equity = total_liab[latest_idx] / equity[latest_idx] if equity[latest_idx] > 0 else 0
                solvency_ratio = total_assets[latest_idx] / total_liab[latest_idx] if total_liab[latest_idx] > 0 else 0
                equity_ratio = equity[latest_idx] / total_assets[latest_idx] if total_assets[latest_idx] > 0 else 0
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Current Ratio", f"{current_ratio:.2f}", 
                              "Healthy" if current_ratio >= 1.5 else ("Warning" if current_ratio >= 1.0 else "⚠️ Critical"),
                              delta="Ideal: >1.5")
                
                with col2:
                    st.metric("Debt-to-Equity", f"{debt_to_equity:.2f}",
                              "Healthy" if debt_to_equity < 2.0 else "⚠️ High",
                              delta="Lower is better")
                
                with col3:
                    st.metric("Solvency Ratio", f"{solvency_ratio:.2f}",
                              "Healthy" if solvency_ratio > 2.0 else "⚠️ Watch",
                              delta="Ideal: >2.0")
                
                with col4:
                    st.metric("Equity Ratio", f"{equity_ratio:.2%}",
                              "Healthy" if equity_ratio > 0.5 else "⚠️ Low",
                              delta="Ideal: >50%")

                # ======================= VISUALIZATIONS =======================
                st.subheader("📈 Financial Trends")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Liquidity trend
                    fig_liquidity = px.line(df, x="Period", y=["Current_Assets", "Current_Liabilities"],
                                            title="Liquidity Trend (Current Assets vs Liabilities)",
                                            markers=True)
                    st.plotly_chart(fig_liquidity, use_container_width=True)
                
                with col2:
                    # Profitability trend
                    fig_profit = px.bar(df, x="Period", y="Net_Profit",
                                       title="Net Profit Trend",
                                       color="Net_Profit",
                                       color_continuous_scale="RdYlGn")
                    st.plotly_chart(fig_profit, use_container_width=True)
                
                col3, col4 = st.columns(2)
                
                with col3:
                    # Debt structure
                    fig_debt = px.line(df, x="Period", y=["Total_Liabilities", "Total_Equity"],
                                      title="Capital Structure (Debt vs Equity)",
                                      markers=True)
                    st.plotly_chart(fig_debt, use_container_width=True)
                
                with col4:
                    # Asset composition (latest period)
                    latest_assets = df.iloc[-1]
                    non_current = max(0, latest_assets["Total_Assets"] - latest_assets["Current_Assets"])
                    fig_assets = px.pie(values=[non_current, latest_assets["Current_Assets"]],
                                       names=["Non-Current Assets", "Current Assets"],
                                       title="Asset Composition (Latest Period)")
                    st.plotly_chart(fig_assets, use_container_width=True)

            except Exception as e:
                st.error(f"❌ **Unexpected Error:** {str(e)}")
                import traceback
                st.write(traceback.format_exc())

# ======================= CSV FALLBACK =======================
uploaded_file = st.file_uploader("Or upload CSV as fallback", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    # ... (your existing calculations, metrics, charts, AI chat)

st.caption("Advisory Health Check • Live on Render")
