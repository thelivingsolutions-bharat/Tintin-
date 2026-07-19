import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime

# Set Page Config for responsive layout
st.set_page_config(page_title="QuantOption Pro Live", layout="wide", initial_sidebar_state="expanded")
st.title("📊 QuantOption Pro - Live Chain Analytics Engine")

# --- SIMULATION FEED GENERATOR ---
def fetch_mock_option_chain(base_spot):
    strikes = range(int(base_spot - 200), int(base_spot + 250), 50)
    data = []
    for s in strikes:
        data.append({
            'strike': s, 'type': 'CE',
            'ltp': max(5.0, (base_spot - s) + 40 + np.random.uniform(-2, 2)),
            'oi': int(1500000 * np.random.uniform(0.7, 1.3)),
            'iv': 12.5 + np.random.uniform(-0.5, 1.0)
        })
        data.append({
            'strike': s, 'type': 'PE',
            'ltp': max(5.0, (s - base_spot) + 35 + np.random.uniform(-2, 2)),
            'oi': int(1400000 * np.random.uniform(0.7, 1.3)),
            'iv': 13.1 + np.random.uniform(-0.5, 1.2)
        })
    return pd.DataFrame(data)

# --- SESSION STATE WAREHOUSE (Remembers data across refreshes) ---
if "snapshot_history" not in st.session_state:
    st.session_state.snapshot_history = {}
if "intraday_log" not in st.session_state:
    st.session_state.intraday_log = pd.DataFrame(columns=["Timestamp", "Spot", "PCR", "Res_Min", "Res_Max", "Sup_Min", "Sup_Max"])
if "running" not in st.session_state:
    st.session_state.running = False

# --- SIDEBAR CONTROL PANEL ---
st.sidebar.header("🔧 Configuration Panel")
target_symbol = st.sidebar.selectbox("Select Underlying Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
broker_api_key = st.sidebar.text_input("Broker API Key", type="password")
client_id = st.sidebar.text_input("Client ID")

col1, col2 = st.sidebar.columns(2)
if col1.button("▶️ START ENGINE", use_container_width=True):
    st.session_state.running = True
if col2.button("⏸️ STOP ENGINE", use_container_width=True):
    st.session_state.running = False

# --- LIVE REFRESH LOOP CONTAINER ---
placeholder = st.empty()

# Simulated changing price base
base_spot = 24300.0

if st.session_state.running:
    while st.session_state.running:
        current_time = datetime.now().strftime("%H:%M:%S")
        base_spot += np.random.uniform(-8, 10)
        
        # Ingest incoming feed
        df_current = fetch_mock_option_chain(base_spot)
        st.session_state.snapshot_history[current_time] = df_current
        
        # Identify snapshot keys for comparison (T1 vs T2)
        keys = list(st.session_state.snapshot_history.keys())
        t1_time = keys[-5] if len(keys) > 5 else keys[0]
        
        df1 = st.session_state.snapshot_history[t1_time].set_index(['strike', 'type'])
        df2 = df_current.set_index(['strike', 'type'])
        
        # Calculate Delta Metrics
        comp_df = pd.DataFrame(index=df2.index)
        comp_df['LTP'] = df2['ltp']
        comp_df['OI'] = df2['oi']
        comp_df['IV'] = df2['iv']
        comp_df['d_Price'] = df2['ltp'] - df1['ltp'].reindex(df2.index)
        comp_df['d_OI'] = df2['oi'] - df1['oi'].reindex(df2.index)
        comp_df.fillna(0, inplace=True)
        
        # Velocity Spike Checking
        avg_change = comp_df['d_OI'].abs().mean()
        comp_df['Velocity_Alert'] = np.where(comp_df['d_OI'].abs() > (2 * avg_change), "🚨 SPIKE", "Normal")
        
        # Trader Vocabulary Classifier Matrix
        conditions = [
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] < 0),
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] < 0)
        ]
        labels = ['Long Buildup', 'Short Buildup', 'Long Unwinding', 'Short Covering']
        comp_df['Buildup_Tag'] = np.select(conditions, labels, default='Neutral')
        comp_df = comp_df.reset_index()
        
        # Structural Zones Calculations
        ce_df = df_current[df_current['type'] == 'CE']
        pe_df = df_current[df_current['type'] == 'PE']
        pcr = pe_df['oi'].sum() / ce_df['oi'].sum() if ce_df['oi'].sum() > 0 else 0
        
        top3_ce = ce_df.nlargest(3, 'oi')['strike'].tolist()
        top3_pe = pe_df.nlargest(3, 'oi')['strike'].tolist()
        res_min, res_max = (min(top3_ce), max(top3_ce)) if top3_ce else (base_spot, base_spot)
        sup_min, sup_max = (min(top3_pe), max(top3_pe)) if top3_pe else (base_spot, base_spot)
        
        # Log entry for intraday plotting
        new_row = pd.DataFrame([{
            "Timestamp": current_time, "Spot": base_spot, "PCR": pcr,
            "Res_Min": res_min, "Res_Max": res_max, "Sup_Min": sup_min, "Sup_Max": sup_max
        }])
        st.session_state.intraday_log = pd.concat([st.session_state.intraday_log, new_row], ignore_index=True)
        
        # --- RENDERING THE VISUAL WEB UI ---
        with placeholder.container():
            # Metrics Dashboard Grid
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("📌 Spot Price", f"{base_spot:.2f}")
            m_col2.metric("📊 PCR Ratio", f"{pcr:.2f}")
            m_col3.metric("🟥 Resistance Channel", f"{res_min} - {res_max}")
            m_col4.metric("🟩 Support Channel", f"{sup_min} - {sup_max}")
            
            st.markdown("---")
            
            # Intraday Multi-Axis Trend Plots
            st.subheader("📈 Intraday Trend Analytics Chart")
            chart_df = st.session_state.intraday_log.set_index("Timestamp")
            st.line_chart(chart_df[["Spot", "Res_Min", "Res_Max", "Sup_Min", "Sup_Max"]])
            st.line_chart(chart_df["PCR"]) # Separate panel tracking PCR drift
            
            st.markdown("---")
            
            # Option Chain Processing Grid Display Table
            st.subheader("⛓️ Processed Live Option Chain Data Matrix")
            
            # Highlight custom builder colors based on build type
            def format_buildup(val):
                color = 'transparent'
                if val == 'Long Buildup': color = '#1e3d22'
                elif val == 'Short Buildup': color = '#3d1e1e'
                elif val == 'Short Covering': color = '#1e2d3d'
                return f'background-color: {color}'
            
            # FIXED: Using modern .map() instead of deprecated .applymap()
            styled_df = comp_df.style.map(format_buildup, subset=['Buildup_Tag'])
            st.dataframe(styled_df, use_container_width=True, height=400)
            
        time.sleep(3) # Dynamic loop tracking interval
else:
    st.info("Engine Idle. Enter your broker metadata panel variables and click 'START ENGINE' to initialize tracking dashboards.")
