import streamlit as st
import pandas as pd
import plotly.express as px
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import requests
from openai import OpenAI
import json
import logging
from typing import Dict, Optional, Tuple

# ======================= LOGGING =======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Advisory Health Check", layout="wide")

# Professional Dark Theme
st.markdown("""
    <style>
    .main {background: #0F1626; color: #E0F2FF;}
    .stApp {background: #0F1626;}
    .stMetric {background: #1A2338; padding: 1rem; border-radius: 12px; border: 1px solid #00D4FF33;}
    h1, h2 {color: #00D4FF;}
    .alert-danger {background: #4D1A1A; color: #FF6B6B; padding: 1rem; border-radius: 8px; border-left: 4px solid #FF6B6B;}
    .alert-warning {background: #4D3D1A; color: #FFD700; padding: 1rem; border-radius: 8px; border-left: 4px solid #FFD700;}
    </style>
""", unsafe_allow_html=True)

st.title("🧠 Advisory Health Check")
st.markdown("**Professional Financial Health & Insolvency Early Warning Tool**")

st.error("⚠️ SCREENING TOOL ONLY — Not professional advice. Always consult a qualified accountant or registered liquidator.")

# ======================= CONFIGURATION =======================
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://advisory-health-check.onrender.com")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REQUEST_TIMEOUT = 30  # seconds

# ======================= SESSION STATE =======================
if "xero_token" not in st.session_state:
    st.session_state.xero_token = None
if "xero_tenant_id" not in st.session_state:
    st.session_state.xero_tenant_id = None
if "xero_data_df" not in st.session_state:
    st.session_state.xero_data_df = None
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = None

# ======================= TOKEN MANAGEMENT =======================
def is_token_expired(token_data: Dict) -> bool:
    """Check if Xero token is expired"""
    if not token_data or "expires_in" not in token_data or "created_at" not in token_data:
        return True
    
    created_at = datetime.fromisoformat(token_data["created_at"])
    expires_in = token_data["expires_in"]
    expiry_time = created_at + timedelta(seconds=expires_in)
    
    # Refresh if expires within 5 minutes
    return datetime.now() > (expiry_time - timedelta(minutes=5))

def refresh_xero_token(token_data: Dict) -> Optional[Dict]:
    """Refresh expired Xero access token"""
    if not token_data.get("refresh_token"):
        logger.warning("No refresh token available")
        return None
    
    try:
        token_url = "https://identity.xero.com/connect/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"]
        }
        
        resp = requests.post(
            token_url,
            data=data,
            auth=(XERO_CLIENT_ID, XERO_CLIENT_SECRET),
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.ok:
            new_token = resp.json()
            new_token["created_at"] = datetime.now().isoformat()
            logger.info("Token refreshed successfully")
            return new_token
        else:
            logger.error(f"Token refresh failed: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Token refresh exception: {e}")
        return None

def get_valid_xero_token() -> Optional[Dict]:
    """Get a valid Xero token, refreshing if necessary"""
    if not st.session_state.xero_token:
        return None
    
    if is_token_expired(st.session_state.xero_token):
        refreshed = refresh_xero_token(st.session_state.xero_token)
        if refreshed:
            st.session_state.xero_token = refreshed
            return refreshed
        else:
            st.session_state.xero_token = None
            return None
    
    return st.session_state.xero_token

# ======================= XERO API HELPERS =======================
def get_xero_tenant_id(token: Dict) -> Optional[str]:
    """Fetch tenant ID from Xero connections"""
    try:
        headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json"
        }
        
        resp = requests.get(
            "https://api.xero.com/connections",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.ok:
            tenants = resp.json()
            if tenants and len(tenants) > 0:
                return tenants[0]["tenantId"]
        else:
            logger.error(f"Failed to get tenant ID: {resp.status_code}")
    except Exception as e:
        logger.error(f"Tenant ID fetch exception: {e}")
    
    return None

def fetch_xero_balance_sheet(token: Dict, tenant_id: str, periods: int = 6) -> Optional[Dict]:
    """Fetch balance sheet report from Xero"""
    try:
        headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Xero-Tenant-Id": tenant_id,
            "Content-Type": "application/json"
        }
        
        resp = requests.get(
            f"https://api.xero.com/api.xro/2.0/Reports/BalanceSheet?periods={periods}",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.ok:
            return resp.json()
        else:
            logger.error(f"Balance sheet fetch failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Balance sheet fetch exception: {e}")
    
    return None

def fetch_xero_profit_loss(token: Dict, tenant_id: str, periods: int = 6) -> Optional[Dict]:
    """Fetch profit and loss report from Xero"""
    try:
        headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Xero-Tenant-Id": tenant_id,
            "Content-Type": "application/json"
        }
        
        resp = requests.get(
            f"https://api.xero.com/api.xro/2.0/Reports/ProfitAndLoss?periods={periods}",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.ok:
            return resp.json()
        else:
            logger.error(f"P&L fetch failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"P&L fetch exception: {e}")
    
    return None

# ======================= DATA PARSING =======================
def parse_xero_report(report_data: Dict) -> pd.DataFrame:
    """Parse Xero API report response into DataFrame"""
    try:
        rows = []
        
        # Handle Xero Report format
        if "Reports" in report_data and len(report_data["Reports"]) > 0:
            report = report_data["Reports"][0]
            
            if "Rows" in report:
                for row in report["Rows"]:
                    parse_xero_row(row, rows, "")
        
        if rows:
            df = pd.DataFrame(rows)
            return df
        else:
            logger.warning("No data extracted from Xero report")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Report parsing exception: {e}")
        return pd.DataFrame()

def parse_xero_row(row: Dict, rows: list, prefix: str = ""):
    """Recursively parse Xero report rows"""
    try:
        if "Cells" in row:
            row_data = {"Account": prefix + row.get("Title", "")}
            
            # Extract values from cells
            for idx, cell in enumerate(row["Cells"]):
                if "Value" in cell:
                    try:
                        row_data[f"Period_{idx}"] = float(cell["Value"].replace(",", ""))
                    except (ValueError, AttributeError):
                        row_data[f"Period_{idx}"] = 0
            
            rows.append(row_data)
        
        # Recursively process child rows
        if "RowType" in row and row["RowType"] == "Section" and "Rows" in row:
            for child_row in row["Rows"]:
                parse_xero_row(child_row, rows, prefix)
    except Exception as e:
        logger.error(f"Row parsing exception: {e}")

def load_csv_data(uploaded_file) -> Optional[pd.DataFrame]:
    """Load and validate CSV data"""
    try:
        df = pd.read_csv(uploaded_file)
        
        # Basic validation
        if df.empty:
            st.error("❌ CSV file is empty")
            return None
        
        logger.info(f"CSV loaded with shape {df.shape}")
        return df
    except Exception as e:
        st.error(f"❌ Error loading CSV: {e}")
        logger.error(f"CSV loading exception: {e}")
        return None

# ======================= FINANCIAL ANALYSIS =======================
def calculate_financial_metrics(bs_df: pd.DataFrame, pl_df: Optional[pd.DataFrame] = None) -> Dict:
    """Calculate key financial health metrics"""
    metrics = {
        "solvency": {},
        "liquidity": {},
        "profitability": {},
        "efficiency": {},
        "warnings": []
    }
    
    try:
        # Extract key figures (assuming standard balance sheet structure)
        assets = bs_df[bs_df["Account"].str.contains("Current Assets|Total Assets", case=False, na=False)]
        liabilities = bs_df[bs_df["Account"].str.contains("Current Liabilities|Total Liabilities", case=False, na=False)]
        equity = bs_df[bs_df["Account"].str.contains("Equity|Total Equity", case=False, na=False)]
        
        if not assets.empty and not liabilities.empty:
            # Solvency Ratios
            total_assets = assets.iloc[0, 1:].sum() if len(assets) > 0 else 0
            total_liabilities = liabilities.iloc[0, 1:].sum() if len(liabilities) > 0 else 0
            
            if total_assets > 0:
                debt_to_assets = total_liabilities / total_assets
                metrics["solvency"]["debt_to_assets"] = debt_to_assets
                
                if debt_to_assets > 0.6:
                    metrics["warnings"].append(f"⚠️ High debt-to-assets ratio: {debt_to_assets:.1%}")
            
            # Liquidity Ratios
            current_assets = assets.iloc[0, 1:].sum() if len(assets) > 0 else 0
            current_liabilities = liabilities.iloc[0, 1:].sum() if len(liabilities) > 0 else 0
            
            if current_liabilities > 0:
                current_ratio = current_assets / current_liabilities
                metrics["liquidity"]["current_ratio"] = current_ratio
                
                if current_ratio < 1.0:
                    metrics["warnings"].append(f"🚨 Current ratio below 1.0: {current_ratio:.2f}")
        
        # Profitability (if P&L available)
        if pl_df is not None and not pl_df.empty:
            revenue = pl_df[pl_df["Account"].str.contains("Revenue|Sales", case=False, na=False)]
            net_income = pl_df[pl_df["Account"].str.contains("Net (Income|Profit)", case=False, na=False)]
            
            if not revenue.empty and not net_income.empty:
                rev_amount = revenue.iloc[0, 1:].sum() if len(revenue) > 0 else 0
                net_amount = net_income.iloc[0, 1:].sum() if len(net_income) > 0 else 0
                
                if rev_amount > 0:
                    profit_margin = net_amount / rev_amount
                    metrics["profitability"]["net_margin"] = profit_margin
                    
                    if profit_margin < 0:
                        metrics["warnings"].append(f"🚨 Negative profit margin: {profit_margin:.1%}")
        
    except Exception as e:
        logger.error(f"Metrics calculation exception: {e}")
        metrics["warnings"].append(f"Error calculating metrics: {e}")
    
    return metrics

def generate_health_score(metrics: Dict) -> Tuple[float, str]:
    """Generate overall health score (0-100)"""
    score = 100
    
    try:
        # Deduct points for poor metrics
        if "debt_to_assets" in metrics.get("solvency", {}):
            ratio = metrics["solvency"]["debt_to_assets"]
            if ratio > 0.8:
                score -= 30
            elif ratio > 0.6:
                score -= 15
        
        if "current_ratio" in metrics.get("liquidity", {}):
            ratio = metrics["liquidity"]["current_ratio"]
            if ratio < 0.5:
                score -= 30
            elif ratio < 1.0:
                score -= 15
        
        if "net_margin" in metrics.get("profitability", {}):
            margin = metrics["profitability"]["net_margin"]
            if margin < -0.1:
                score -= 25
            elif margin < 0:
                score -= 15
        
        # Ensure score is between 0-100
        score = max(0, min(100, score))
        
        # Determine health status
        if score >= 80:
            status = "🟢 HEALTHY"
        elif score >= 60:
            status = "🟡 AT RISK"
        elif score >= 40:
            status = "🔴 DANGER"
        else:
            status = "⚫ CRITICAL"
        
    except Exception as e:
        logger.error(f"Health score calculation exception: {e}")
        score = 50
        status = "❓ UNABLE TO CALCULATE"
    
    return score, status

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
    
    if XERO_CLIENT_ID and XERO_CLIENT_SECRET:
        if not st.session_state.xero_token:
            if st.button("Connect to Xero", use_container_width=True):
                scope = "accounting.reports.balancesheet.read accounting.reports.profitandloss.read accounting.settings.read offline_access"
                auth_url = (
                    f"https://login.xero.com/identity/connect/authorize?"
                    f"response_type=code&client_id={XERO_CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                    f"&scope={scope.replace(' ', '%20')}&state=xero123"
                )
                st.markdown(f"[🔐 Connect to Xero]({auth_url})", unsafe_allow_html=True)
        else:
            st.success("✅ Connected to Xero")
            if st.button("Disconnect", use_container_width=True):
                st.session_state.xero_token = None
                st.session_state.xero_tenant_id = None
                st.rerun()
    else:
        st.warning("⚠️ Xero credentials not configured")

# ======================= HANDLE OAUTH CALLBACK =======================
query_params = st.query_params
if "code" in query_params and st.session_state.xero_token is None:
    with st.spinner("🔄 Connecting to Xero..."):
        try:
            code = query_params["code"]
            state = query_params.get("state")
            
            # CSRF Protection
            if state != "xero123":
                st.error("❌ Invalid state parameter")
            else:
                token_url = "https://identity.xero.com/connect/token"
                data = {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI
                }
                
                resp = requests.post(
                    token_url,
                    data=data,
                    auth=(XERO_CLIENT_ID, XERO_CLIENT_SECRET),
                    timeout=REQUEST_TIMEOUT
                )
                
                if resp.ok:
                    token = resp.json()
                    token["created_at"] = datetime.now().isoformat()
                    st.session_state.xero_token = token
                    
                    # Get tenant ID
                    tenant_id = get_xero_tenant_id(token)
                    if tenant_id:
                        st.session_state.xero_tenant_id = tenant_id
                    
                    st.success("🎉 Successfully connected to Xero!")
                    st.rerun()
                else:
                    st.error(f"❌ Token exchange failed: {resp.text}")
                    logger.error(f"Token exchange error: {resp.text}")
        except Exception as e:
            st.error(f"❌ Connection error: {e}")
            logger.error(f"OAuth callback exception: {e}")

# ======================= MAIN CONTENT =======================
tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📥 Data Import", "💡 Analysis", "📄 Report"])

with tab1:
    st.subheader("Financial Health Dashboard")
    
    if st.session_state.xero_data_df is not None and not st.session_state.xero_data_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        if st.session_state.analysis_results:
            metrics = st.session_state.analysis_results
            score, status = generate_health_score(metrics)
            
            with col1:
                st.metric("Health Score", f"{score:.0f}/100", status)
            
            with col2:
                if "debt_to_assets" in metrics.get("solvency", {}):
                    st.metric("Debt-to-Assets", f"{metrics['solvency']['debt_to_assets']:.1%}")
            
            with col3:
                if "current_ratio" in metrics.get("liquidity", {}):
                    st.metric("Current Ratio", f"{metrics['liquidity']['current_ratio']:.2f}")
            
            with col4:
                if "net_margin" in metrics.get("profitability", {}):
                    st.metric("Net Margin", f"{metrics['profitability']['net_margin']:.1%}")
            
            st.divider()
            
            # Display warnings
            if metrics.get("warnings"):
                st.markdown("### ⚠️ Health Warnings")
                for warning in metrics["warnings"]:
                    if "🚨" in warning:
                        st.markdown(f'<div class="alert-danger">{warning}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="alert-warning">{warning}</div>', unsafe_allow_html=True)
            
            # Display data table
            st.markdown("### Financial Data")
            st.dataframe(st.session_state.xero_data_df, use_container_width=True)
    else:
        st.info("📋 Import financial data to view dashboard")

with tab2:
    st.subheader("Data Import")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Xero Integration")
        if st.session_state.xero_token:
            if st.button("📥 Pull Latest Data from Xero", use_container_width=True):
                with st.spinner("🔄 Fetching data from Xero..."):
                    try:
                        token = get_valid_xero_token()
                        
                        if not token:
                            st.error("❌ Token invalid or expired. Please reconnect to Xero.")
                        elif not st.session_state.xero_tenant_id:
                            st.error("❌ Tenant ID not available. Please reconnect to Xero.")
                        else:
                            # Fetch reports
                            bs_data = fetch_xero_balance_sheet(token, st.session_state.xero_tenant_id)
                            pl_data = fetch_xero_profit_loss(token, st.session_state.xero_tenant_id)
                            
                            if bs_data:
                                # Parse balance sheet
                                bs_df = parse_xero_report(bs_data)
                                
                                if not bs_df.empty:
                                    st.session_state.xero_data_df = bs_df
                                    
                                    # Calculate metrics
                                    pl_df = parse_xero_report(pl_data) if pl_data else None
                                    metrics = calculate_financial_metrics(bs_df, pl_df)
                                    st.session_state.analysis_results = metrics
                                    
                                    st.success("✅ Data pulled from Xero!")
                                    st.balloons()
                                else:
                                    st.error("❌ Could not parse balance sheet data")
                            else:
                                st.error("❌ Failed to fetch balance sheet")
                    
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                        logger.error(f"Xero data pull exception: {e}")
        else:
            st.info("🔗 Connect to Xero in the sidebar to import data")
    
    with col2:
        st.markdown("### CSV Upload")
        uploaded_file = st.file_uploader("Upload CSV as fallback", type=["csv"])
        
        if uploaded_file:
            df = load_csv_data(uploaded_file)
            
            if df is not None:
                st.session_state.xero_data_df = df
                
                # Try to calculate metrics
                metrics = calculate_financial_metrics(df)
                st.session_state.analysis_results = metrics
                
                st.success("✅ CSV loaded successfully!")
                st.dataframe(df.head(10), use_container_width=True)

with tab3:
    st.subheader("Financial Analysis")
    
    if st.session_state.analysis_results:
        metrics = st.session_state.analysis_results
        score, status = generate_health_score(metrics)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Solvency")
            if metrics.get("solvency"):
                for key, value in metrics["solvency"].items():
                    st.write(f"**{key.replace('_', ' ').title()}:** {value:.2%}")
            else:
                st.info("No solvency metrics available")
        
        with col2:
            st.markdown("### Liquidity")
            if metrics.get("liquidity"):
                for key, value in metrics["liquidity"].items():
                    st.write(f"**{key.replace('_', ' ').title()}:** {value:.2f}")
            else:
                st.info("No liquidity metrics available")
        
        st.divider()
        
        st.markdown("### Profitability")
        if metrics.get("profitability"):
            for key, value in metrics["profitability"].items():
                st.write(f"**{key.replace('_', ' ').title()}:** {value:.2%}")
        else:
            st.info("No profitability metrics available")
        
        if metrics.get("warnings"):
            st.divider()
            st.markdown("### ⚠️ Risk Indicators")
            for warning in metrics["warnings"]:
                st.warning(warning)
    else:
        st.info("📊 Import data to view analysis")

with tab4:
    st.subheader("Generate Report")
    
    if st.session_state.analysis_results and st.session_state.xero_data_df is not None:
        col1, col2 = st.columns([3, 1])
        
        with col1:
            report_title = st.text_input("Report Title", f"Advisory Health Check - {company_name}")
        
        with col2:
            if st.button("📄 Generate PDF", use_container_width=True):
                try:
                    with st.spinner("📄 Generating PDF..."):
                        # Create PDF (basic implementation)
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.set_font("Arial", "B", 16)
                        
                        pdf.cell(0, 10, report_title, ln=True)
                        pdf.set_font("Arial", "", 10)
                        pdf.cell(0, 10, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
                        
                        metrics = st.session_state.analysis_results
                        score, status = generate_health_score(metrics)
                        
                        pdf.ln(10)
                        pdf.cell(0, 10, f"Health Score: {score:.0f}/100 - {status}", ln=True)
                        
                        # Save PDF
                        pdf_path = "/tmp/advisory_health_check.pdf"
                        pdf.output(pdf_path)
                        
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                label="📥 Download PDF",
                                data=f.read(),
                                file_name=f"health_check_{datetime.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf"
                            )
                        
                        st.success("✅ PDF generated successfully!")
                
                except Exception as e:
                    st.error(f"❌ Error generating PDF: {e}")
                    logger.error(f"PDF generation exception: {e}")
    else:
        st.info("📊 Import data and run analysis to generate report")

st.divider()
st.caption("Advisory Health Check • Live on Render • v2.1")
