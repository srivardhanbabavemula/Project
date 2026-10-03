"""
MLOps Dashboard for Fraud Guard
Powered by Streamlit
"""

import os
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2.extras import RealDictCursor

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Fraud Guard MLOps Platform",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for "Rich Aesthetics" (Glassmorphism & Dark Mode feel)
st.markdown("""
<style>
    /* Dark Theme Adjustments */
    .stApp {
        background-color: #0f172a;
        color: #f8fafc;
    }
    
    /* Metrics Cards */
    div[data-testid="metric-container"] {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 1rem;
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #e2e8f0;
        font-family: 'Inter', sans-serif;
    }
    h1 {
        background: -webkit-linear-gradient(45deg, #3b82f6, #8b5cf6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        margin-bottom: 0.5rem;
    }
    
    /* DataFrame Tables */
    .stDataFrame {
        border-radius: 12px !important;
        overflow: hidden;
    }
    
    /* Badges */
    .badge {
        padding: 0.2rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-production { background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-challenger { background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.3); }
    .badge-staging    { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .badge-archived   { background: rgba(100, 116, 139, 0.2); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }
</style>
""", unsafe_allow_html=True)


# --- DATABASE CONNECTION ---
@st.cache_resource
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5433")),
            database=os.environ.get("DB_NAME", "fraud_detection"),
            user=os.environ.get("DB_USER", "frauduser"),
            password=os.environ.get("DB_PASSWORD", "fraudpass123")
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None

def fetch_data(query: str):
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return pd.DataFrame(rows)
    except Exception as e:
        conn.rollback()
        st.error(f"Query failed: {e}")
        return pd.DataFrame()


# --- HEADER ---
st.markdown("<h1>Fraud Guard MLOps Platform</h1>", unsafe_allow_html=True)
st.markdown("Monitor model registry, live A/B experiments, and data drift all in one place.", unsafe_allow_html=True)
st.divider()

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["🚀 Model Registry", "🧪 A/B Testing", "🚨 Data Drift Monitoring"])

# ==========================================
# TAB 1: MODEL REGISTRY
# ==========================================
with tab1:
    st.markdown("### Versioned XGBoost Models")
    df_models = fetch_data("SELECT version, stage, created_at, promoted_at, training_rows, fraud_rate, metrics FROM model_registry ORDER BY created_at DESC")
    
    if not df_models.empty:
        col1, col2, col3, col4 = st.columns(4)
        prod_count = len(df_models[df_models['stage'] == 'production'])
        chal_count = len(df_models[df_models['stage'] == 'challenger'])
        
        col1.metric("Total Models", len(df_models))
        col2.metric("Production Champion", prod_count)
        col3.metric("Active Challengers", chal_count)
        
        # Display the registry
        st.markdown("#### Model Directory")
        
        # Format the dataframe for display
        display_df = df_models.copy()
        display_df['metrics'] = display_df['metrics'].apply(lambda x: f"ROC-AUC: {x.get('roc_auc', 0):.3f} | PR-AUC: {x.get('pr_auc', 0):.3f}" if isinstance(x, dict) else "N/A")
        display_df['created_at'] = pd.to_datetime(display_df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
        
        # Custom HTML table for badges
        table_html = "<table style='width:100%; border-collapse: collapse; margin-top: 1rem;'>"
        table_html += "<tr style='border-bottom: 1px solid rgba(255,255,255,0.1);'><th style='text-align:left; padding:0.5rem;'>Version</th><th style='text-align:left; padding:0.5rem;'>Stage</th><th style='text-align:left; padding:0.5rem;'>Created At</th><th style='text-align:left; padding:0.5rem;'>Metrics</th></tr>"
        
        for _, row in display_df.iterrows():
            stage = row['stage']
            badge_class = f"badge-{stage}"
            badge_html = f"<span class='badge {badge_class}'>{stage}</span>"
            table_html += f"<tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding:0.7rem;'><code>{row['version']}</code></td><td style='padding:0.7rem;'>{badge_html}</td><td style='padding:0.7rem;'>{row['created_at']}</td><td style='padding:0.7rem;'>{row['metrics']}</td></tr>"
        
        table_html += "</table>"
        st.markdown(table_html, unsafe_allow_html=True)
        
        # Training Metrics Chart
        if len(df_models) > 1:
            st.markdown("#### Model Performance Trend")
            
            # Extract ROC-AUC
            chart_df = df_models.copy()
            chart_df['roc_auc'] = chart_df['metrics'].apply(lambda x: x.get('roc_auc', 0) if isinstance(x, dict) else 0)
            chart_df = chart_df.sort_values('created_at')
            
            fig = px.line(chart_df, x='version', y='roc_auc', markers=True,
                          title="ROC-AUC Score over Versions",
                          color_discrete_sequence=['#3b82f6'])
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
                              font_color='#e2e8f0', margin=dict(l=20, r=20, t=40, b=20))
            fig.update_yaxes(gridcolor='rgba(255,255,255,0.1)', range=[min(chart_df['roc_auc'])-0.05, 1.0])
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("No models registered yet. Run the training pipeline to register a model.")

# ==========================================
# TAB 2: A/B TESTING
# ==========================================
with tab2:
    st.markdown("### Active Shadow Deployments & A/B Tests")
    
    df_experiments = fetch_data("SELECT * FROM model_experiments WHERE status = 'active'")
    
    if not df_experiments.empty:
        exp = df_experiments.iloc[0]
        
        st.markdown(f"**Current Experiment**: `{exp['description'] or 'Unnamed'}`")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
            <div style='background: rgba(34, 197, 94, 0.1); border-left: 4px solid #22c55e; padding: 1rem; border-radius: 4px;'>
                <h4 style='color: #22c55e; margin: 0;'>🏆 Champion Model</h4>
                <p style='font-family: monospace; font-size: 1.2rem; margin: 0.5rem 0 0 0;'>{exp['champion_version']}</p>
                <p style='color: #94a3b8; font-size: 0.9rem; margin: 0;'>Receiving {(1 - exp['traffic_pct']) * 100:.1f}% of traffic</p>
            </div>
            """, unsafe_allow_html=True)
            
        with col2:
            st.markdown(f"""
            <div style='background: rgba(234, 179, 8, 0.1); border-left: 4px solid #eab308; padding: 1rem; border-radius: 4px;'>
                <h4 style='color: #eab308; margin: 0;'>⚔️ Challenger Model</h4>
                <p style='font-family: monospace; font-size: 1.2rem; margin: 0.5rem 0 0 0;'>{exp['challenger_version']}</p>
                <p style='color: #94a3b8; font-size: 0.9rem; margin: 0;'>Receiving {exp['traffic_pct'] * 100:.1f}% of traffic</p>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Traffic Split Visual
        fig = go.Figure(data=[
            go.Pie(labels=['Champion', 'Challenger'], 
                   values=[1 - exp['traffic_pct'], exp['traffic_pct']],
                   hole=.6,
                   marker_colors=['#22c55e', '#eab308'])
        ])
        fig.update_layout(title_text="Live Traffic Split", 
                          plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                          font_color='#e2e8f0', margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.info("No active A/B experiments running. All traffic is routed to the Champion model.")
        
        # Show history
        st.markdown("#### Experiment History")
        df_history = fetch_data("SELECT champion_version, challenger_version, traffic_pct, started_at, stopped_at, description FROM model_experiments WHERE status = 'stopped' ORDER BY started_at DESC LIMIT 5")
        if not df_history.empty:
            st.dataframe(df_history, use_container_width=True, hide_index=True)


# ==========================================
# TAB 3: DATA DRIFT MONITORING
# ==========================================
with tab3:
    st.markdown("### Evidently Data Drift Reports")
    
    df_drift = fetch_data("SELECT * FROM drift_reports ORDER BY run_at DESC")
    
    if not df_drift.empty:
        latest = df_drift.iloc[0]
        
        # Status Card
        drift_detected = latest['drift_detected']
        color = "#ef4444" if drift_detected else "#22c55e"
        icon = "🚨" if drift_detected else "✅"
        status_text = "DRIFT DETECTED" if drift_detected else "NO DRIFT"
        
        st.markdown(f"""
        <div style='background: {color}20; border: 1px solid {color}50; padding: 1.5rem; border-radius: 12px; text-align: center; margin-bottom: 2rem;'>
            <h2 style='color: {color}; margin: 0;'>{icon} {status_text}</h2>
            <p style='color: #94a3b8; margin: 0.5rem 0 0 0;'>Last checked: {pd.to_datetime(latest['run_at']).strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p style='color: #cbd5e1; margin: 0.2rem 0 0 0;'>Model: <code>{latest['model_version']}</code></p>
        </div>
        """, unsafe_allow_html=True)
        
        # Key Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Features Drifted", f"{latest['n_drifted']} / {latest['n_features']}")
        col2.metric("Drift Share", f"{latest['drift_share'] * 100:.1f}%")
        
        action_color = "normal" if latest['action_taken'] == 'none' else "inverse"
        col3.metric("Action Taken", latest['action_taken'].upper())
        col4.metric("Reference Rows", f"{latest['n_reference_rows']:,}")
        
        # Drifted Features List
        if latest['n_drifted'] > 0:
            st.markdown("#### ⚠️ Drifted Features")
            drifted_list = latest['drifted_features']
            if isinstance(drifted_list, list):
                for feature in drifted_list:
                    st.markdown(f"- `{feature}`")
        
        # History Chart
        if len(df_drift) > 1:
            st.markdown("#### Drift Trend")
            
            chart_df = df_drift.sort_values('run_at').copy()
            chart_df['run_at'] = pd.to_datetime(chart_df['run_at'])
            
            fig = px.area(chart_df, x='run_at', y='drift_share', 
                          title="Share of Drifted Features over Time",
                          color_discrete_sequence=['#ef4444'])
            # Add threshold line
            fig.add_hline(y=0.2, line_dash="dash", line_color="yellow", annotation_text="Rollback Threshold (20%)")
            
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
                              font_color='#e2e8f0', margin=dict(l=20, r=20, t=40, b=20))
            fig.update_yaxes(gridcolor='rgba(255,255,255,0.1)', range=[0, max(0.5, chart_df['drift_share'].max() + 0.1)])
            fig.update_xaxes(title="Run Date")
            st.plotly_chart(fig, use_container_width=True)
            
    else:
        st.info("No drift reports available. Run `python ml/drift_monitor.py` to generate one.")

