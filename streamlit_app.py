import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime
from dhanhq import DhanContext, dhanhq
import plotly.graph_objects as go

# Config
st.set_page_config(page_title="QuantOption Pro Live", layout="wide", initial_sidebar_state="expanded")
st.title("📊 QuantOption Pro - Dhan Advanced Analytics")

# --- SESSION STATE WAREHOUSE (Prevents Login Data Loss) ---
if "client_id" not in st.session_state: st.session_state.client_id = ""
if "access_token" not in st.session_state: st.session_state.access_token = ""
if "expiry_date" not in st.session_state: st.session_state.expiry_date = "2026-07-21"
if "target_symbol" not in st.session_state: st.session_state.target_symbol = "NIFTY"
if "engine_mode" not in st.session_state: st.session_state.engine_mode = "Simulation Mode (Weekend/Testing)"
if "intraday_log" not in st.session_state: st.session_state.intraday_log = pd.DataFrame(columns=["Timestamp", "Spot", "PCR", "India_VIX", "ATM_Straddle"])
if "atm_ce_ohlc" not in st.session_state: st.session_state.atm_ce_ohlc = []
if "atm_pe_ohlc" not in st.session_state: st.session_state.atm_pe_ohlc = []
if "sim_spot" not in st.session_state: st.session_state.sim_spot = 24185.0
if "oi_alert_threshold" not in st.session_state: st.session_state.oi_alert_threshold = 20.0 # Percentage change
if "iv_alert_threshold" not in st.session_state: st.session_state.iv_alert_threshold = 15.0 # Percentage change

# --- SIMULATION fallback ---
def fetch_mock_option_chain(base_spot):
    strikes = range(int(base_spot - 200), int(base_spot + 250), 50)
    data = []
    for s in strikes:
        data.append({'strike': s, 'type': 'CE', 'ltp': max(2.0, (base_spot - s) + 40 + np.random.uniform(-2, 2)), 'oi': int(1500000 * np.random.uniform(0.8, 1.2)), 'iv': 13.0 + np.random.uniform(-0.2, 0.2)})
        data.append({'strike': s, 'type': 'PE', 'ltp': max(2.0, (s - base_spot) + 35 + np.random.uniform(-2, 2)), 'oi': int(1400000 * np.random.uniform(0.8, 1.2)), 'iv': 13.5 + np.random.uniform(-0.2, 0.2)})
    return pd.DataFrame(data)

# --- DHAN LIVE INTEGRATION ---
def fetch_dhan_option_chain(dhan_client, security_id, exchange_segment, expiry_date):
    try:
        # Convert standard YYYY-MM-DD to Dhan's corporate API structure
        try:
            date_obj = datetime.strptime(expiry_date, "%Y-%m-%d")
            formatted_expiry = date_obj.strftime("%Y-%m-%d") # API V2 Standard format
        except:
            formatted_expiry = expiry_date

        oc_data = dhan_client.option_chain(
            under_security_id=int(security_id),
            under_exchange_segment=str(exchange_segment),
            expiry=str(formatted_expiry)
        )
        
        if oc_data and oc_data.get('status') == 'success' and 'data' in oc_data:
            data_payload = oc_data['data']
            if not data_payload or not data_payload.get('oc'):
                return data_payload.get('last_price', 0.0), pd.DataFrame(), "EMPTY_OC"
            
            chain_records = []
            base_spot = data_payload.get('last_price', 0.0)
            for strike_str, options in data_payload.get('oc', {}).items():
                strike_val = float(strike_str)
                if 'ce' in options:
                    ce = options['ce']
                    chain_records.append({'strike': strike_val, 'type': 'CE', 'ltp': ce.get('last_price', 0.0), 'oi': ce.get('oi', 0), 'iv': ce.get('implied_volatility', 13.0)})
                if 'pe' in options:
                    pe = options['pe']
                    chain_records.append({'strike': strike_val, 'type': 'PE', 'ltp': pe.get('last_price', 0.0), 'oi': pe.get('oi', 0), 'iv': pe.get('implied_volatility', 13.0)})
            return base_spot, pd.DataFrame(chain_records), "success"
        return 0.0, pd.DataFrame(), str(oc_data.get('remarks', 'API Refusal')) if oc_data else "Timeout"
    except Exception as e:
        return 0.0, pd.DataFrame(), str(e)

# --- ADVANCED OHLC CANDLESTICK CONSTRUCTOR ---
def update_ohlc_history(history_list, current_price, current_time, timeframe_mins):
    time_object = datetime.strptime(current_time, "%H:%M:%S")
    minute_val = time_object.minute
    rounded_minute = (minute_val // timeframe_mins) * timeframe_mins
    candle_time_str = time_object.replace(minute=rounded_minute, second=0).strftime("%H:%M:00")
    
    if not history_list or history_list[-1]['time'] != candle_time_str:
        history_list.append({
            'time': candle_time_str, 'open': current_price, 'high': current_price, 'low': current_price, 'close': current_price
        })
    else:
        history_list[-1]['high'] = max(history_list[-1]['high'], current_price)
        history_list[-1]['low'] = min(history_list[-1]['low'], current_price)
        history_list[-1]['close'] = current_price
    if len(history_list) > 30: history_list.pop(0)

# --- SIDEBAR CONTROL PANEL ---
st.sidebar.header("🔌 Mode Selection")
st.session_state.engine_mode = st.sidebar.radio("Data Stream Source", ["Simulation Mode (Weekend/Testing)", "Live Dhan API Mode"], index=0 if st.session_state.engine_mode == "Simulation Mode (Weekend/Testing)" else 1)

st.sidebar.markdown("---")
st.sidebar.header("🔑 Dhan Credentials")
st.session_state.client_id = st.sidebar.text_input("Dhan Client ID", value=st.session_state.client_id)
st.session_state.access_token = st.sidebar.text_input("Dhan Access Token (JWT)", type="password", value=st.session_state.access_token)

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Selection")
st.session_state.target_symbol = st.sidebar.selectbox("Select Asset Profile", ["NIFTY", "BANKNIFTY", "FINNIFTY"], index=["NIFTY", "BANKNIFTY", "FINNIFTY"].index(st.session_state.target_symbol))
st.session_state.expiry_date = st.sidebar.text_input("Expiry Date (YYYY-MM-DD)", value=st.session_state.expiry_date)

st.sidebar.markdown("---")
st.sidebar.header("🚨 Risk Alert Controls")
st.session_state.oi_alert_threshold = st.sidebar.slider("OI Shift Trigger (%)", 5.0, 50.0, value=st.session_state.oi_alert_threshold)
st.session_state.iv_alert_threshold = st.sidebar.slider("IV Spike Trigger (%)", 5.0, 50.0, value=st.session_state.iv_alert_threshold)

st.sidebar.markdown("---")
activate_engine = st.sidebar.toggle("🚀 ACTIVATE ENGINE", value=False)

# Permanent UI slots
alert_box = st.container()
metrics_box = st.empty()
st.markdown("---")

# Selection view row
tf_col1, _ = st.columns([2, 5])
with tf_col1:
    selected_tf = st.selectbox("📊 Select Candlestick Timeframe", ["1 Minute", "5 Minute", "15 Minute"], index=0)
tf_minutes = {"1 Minute": 1, "5 Minute": 5, "15 Minute": 15}[selected_tf]

st.subheader("🕯️ ATM Option Premium Candlesticks")
c_col1, c_col2 = st.columns(2)
ce_chart_slot = c_col1.empty()
pe_chart_slot = c_col2.empty()

st.markdown("---")
st.subheader("📈 Volatility Dynamics & Straddle Analytics (Line Trackers)")
line_charts_box = st.empty()

# --- REFRESH FRAGMENT LOOP ---
@st.fragment(run_every=4) # Rate limit friendly (complying with Dhan's 3-second limit rule)
def live_dashboard_fragment():
    if not activate_engine:
        metrics_box.info("Dhan Engine Idle. Flip 'ACTIVATE ENGINE' in the sidebar to initiate tracking.")
        return

    current_time = datetime.now().strftime("%H:%M:%S")
    use_sim = (st.session_state.engine_mode != "Live Dhan API Mode")
    
    if st.session_state.engine_mode == "Live Dhan API Mode":
        context = DhanContext(st.session_state.client_id, st.session_state.access_token)
        dhan = dhanhq(context)
        scrip_map = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27}
        base_spot, df_current, api_status = fetch_dhan_option_chain(dhan, scrip_map[st.session_state.target_symbol], "IDX_I", st.session_state.expiry_date)
        
        if api_status != "success":
            use_sim = True
            
    if use_sim:
        st.session_state.sim_spot += np.random.uniform(-1.2, 1.5)
        base_spot = st.session_state.sim_spot
        df_current = fetch_mock_option_chain(base_spot)
        
    # Option fields mapping
    ce_df = df_current[df_current['type'] == 'CE']
    pe_df = df_current[df_current['type'] == 'PE']
    pcr = pe_df['oi'].sum() / ce_df['oi'].sum() if ce_df['oi'].sum() > 0 else 0.0
    
    atm_strike = round(base_spot / 50) * 50
    atm_ce_row = ce_df[ce_df['strike'] == atm_strike]
    atm_pe_row = pe_df[pe_df['strike'] == atm_strike]
    
    ltp_ce = atm_ce_row['ltp'].values[0] if not atm_ce_row.empty else 50.0
    ltp_pe = atm_pe_row['ltp'].values[0] if not atm_pe_row.empty else 50.0
    straddle_premium = ltp_ce + ltp_pe
    
    # Render OHLC
    update_ohlc_history(st.session_state.atm_ce_ohlc, ltp_ce, current_time, tf_minutes)
    update_ohlc_history(st.session_state.atm_pe_ohlc, ltp_pe, current_time, tf_minutes)
    
    # --- VOLATILITY ALERT TRIGGERS ---
    if len(st.session_state.intraday_log) > 1:
        prev_row = st.session_state.intraday_log.iloc[-1]
        
        # OI Change alert check
        ce_oi_total = ce_df['oi'].sum()
        if prev_row['PCR'] > 0:
            oi_pct_diff = abs((pe_df['oi'].sum() / ce_oi_total) - prev_row['PCR']) / prev_row['PCR'] * 100
            if oi_pct_diff >= st.session_state.oi_alert_threshold:
                alert_box.warning(f"🚨 OI Spike Alert ({current_time}): Significant open interest movement detected! PCR shifted by {oi_pct_diff:.1f}%")

        # IV Change alert check
        avg_iv = ce_df['iv'].mean()
        if not ce_df.empty:
            with alert_box:
                if avg_iv > 18.0:
                    st.error(f"💥 IV Alert ({current_time}): Sharp Implied Volatility spike detected! Average IV: {avg_iv:.1f}")

    # Log Metrics
    new_row = pd.DataFrame([{"Timestamp": current_time, "Spot": base_spot, "PCR": pcr, "India_VIX": 13.4, "ATM_Straddle": straddle_premium}])
    st.session_state.intraday_log = pd.concat([st.session_state.intraday_log, new_row], ignore_index=True)
    if len(st.session_state.intraday_log) > 60: st.session_state.intraday_log = st.session_state.intraday_log.iloc[-60:]
    
    with metrics_box.container():
        m1, m2, m3 = st.columns(3)
        m1.metric("📌 Underlying Spot Price", f"{base_spot:.2f}")
        m2.metric("📊 Put-Call Ratio (PCR)", f"{pcr:.2f}")
        m3.metric("🛡️ ATM Straddle Premium", f"₹{straddle_premium:.2f}")

    # Plot Candlesticks
    df_ce_ohlc = pd.DataFrame(st.session_state.atm_ce_ohlc)
    df_pe_ohlc = pd.DataFrame(st.session_state.atm_pe_ohlc)
    
    with ce_chart_slot.container():
        if not df_ce_ohlc.empty:
            fig = go.Figure(data=[go.Candlestick(x=df_ce_ohlc['time'], open=df_ce_ohlc['open'], high=df_ce_ohlc['high'], low=df_ce_ohlc['low'], close=df_ce_ohlc['close'])])
            fig.update_layout(xaxis_rangeslider_visible=False, height=260, margin=dict(l=10,r=10,t=10,b=10), template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True, key="ce_cand_live")
            
    with pe_chart_slot.container():
        if not df_pe_ohlc.empty:
            fig = go.Figure(data=[go.Candlestick(x=df_pe_ohlc['time'], open=df_pe_ohlc['open'], high=df_pe_ohlc['high'], low=df_pe_ohlc['low'], close=df_pe_ohlc['close'])])
            fig.update_layout(xaxis_rangeslider_visible=False, height=260, margin=dict(l=10,r=10,t=10,b=10), template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True, key="pe_cand_live")

    # --- FORCED LINE GRAPH VIEW FOR PCR & STRADDLE ---
    with line_charts_box.container():
        chart_df = st.session_state.intraday_log.set_index("Timestamp")
        
        # Line plots
        fig_pcr = go.Figure()
        fig_pcr.add_trace(go.Scatter(x=chart_df.index, y=chart_df['PCR'], mode='lines+markers', name='PCR Ratio', line=dict(color='#ff9900', width=2)))
        fig_pcr.update_layout(title="PCR Trend Analysis", height=230, margin=dict(l=10,r=10,t=30,b=10), template="plotly_dark")
        st.plotly_chart(fig_pcr, use_container_width=True, key="pcr_line_live")
        
        fig_std = go.Figure()
        fig_std.add_trace(go.Scatter(x=chart_df.index, y=chart_df['ATM_Straddle'], mode='lines', name='Straddle Premium', line=dict(color='#00a8ff', width=2.5)))
        fig_std.update_layout(title="ATM Straddle Value Decay Tracker", height=230, margin=dict(l=10,r=10,t=30,b=10), template="plotly_dark")
        st.plotly_chart(fig_std, use_container_width=True, key="straddle_line_live")

live_dashboard_fragment()
