import streamlit as st
import pandas as pd
from sqlalchemy import text
from db import obtener_conexion
import hashlib
from datetime import date

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MyTaller", 
    layout="wide",
    initial_sidebar_state="expanded" if st.session_state.get('user_logged', False) else "collapsed"
)

# 2. FIX DEFINITIVO PARA LA FLECHA DE LA BARRA LATERAL
st.markdown("""
    <style>
    /* Ocultar el menú nativo de Streamlit (tres puntos, Fork, Deploy) sin romper la cabecera */
    [data-testid="stToolbar"], #MainMenu, footer {
        visibility: hidden !important;
        height: 0px !important;
    }

    /* Mantener el contenedor del Header transparente pero funcional */
    [data-testid="stHeader"] {
        background-color: transparent !important;
        z-index: 100 !important;
    }

    /* FORZAR VISIBILIDAD DEL BOTÓN DE EXPANDIR/COLAPSAR BARRA LATERAL */
    [data-testid="stSidebarCollapsedControl"], 
    [data-testid="stSidebarCollapseButton"] {
        visibility: visible !important;
        display: flex !important;
        z-index: 999999 !important;
        opacity: 1 !important;
    }

    /* Animación suave de entrada */
    @keyframes fade-in-up {
        0% { opacity: 0; transform: translateY(20px); }
        100% { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stAppViewBlockContainer"] {
        animation: fade-in-up 0.6s ease-out;
    }
    div[data-testid="stVerticalBlock"] > div {
        animation: fade-in-up 0.5s ease-out;
    }
    </style>
""", unsafe_allow_html=True)
