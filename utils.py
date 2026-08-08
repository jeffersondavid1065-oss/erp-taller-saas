import streamlit as st


def aplicar_estilos():
    """
    Aplica los estilos CSS globales de MyAlmacén en cualquier página.
    Usa un div overlay para bloquear la esquina derecha del header
    sin tapar el botón de colapso del sidebar.
    """
    st.markdown("""
        <style>
        /* Ocultar toolbar (GitHub, deploy) */
        [data-testid="stToolbar"] { display: none !important; }

        /* Ocultar decoración */
        [data-testid="stDecoration"] { display: none !important; }

        /* Ocultar menú principal (3 puntos) */
        #MainMenu { visibility: hidden !important; }

        /* Ocultar footer */
        footer { visibility: hidden !important; }

        /* Ocultar nav del sidebar (lista de páginas)
           pero NO el botón de colapso/expand */
        [data-testid="stSidebarNav"] { display: none !important; }

        /* Div overlay que bloquea la esquina derecha */
        #header-blocker {
            position: fixed;
            top: 0;
            right: 0;
            width: 320px;
            height: 60px;
            z-index: 99999;
            pointer-events: all;
        }

        @keyframes fade-in-up {
            0% { opacity: 0; transform: translateY(20px); }
            100% { opacity: 1; transform: translateY(0); }
        }
        [data-testid="stAppViewBlockContainer"] { animation: fade-in-up 0.6s ease-out !important; }
        div[data-testid="stVerticalBlock"] > div { animation: fade-in-up 0.5s ease-out !important; }
        </style>

        <div id="header-blocker"></div>
        <script>
        function ajustarColorBlocker() {
            const blocker = document.getElementById('header-blocker');
            if (!blocker) return;
            const bodyBg = getComputedStyle(document.documentElement)
                .getPropertyValue('--background-color') || 
                getComputedStyle(document.body).backgroundColor;
            blocker.style.backgroundColor = bodyBg || '#0e1117';
        }
        setTimeout(ajustarColorBlocker, 300);
        setTimeout(ajustarColorBlocker, 1000);
        setTimeout(ajustarColorBlocker, 2000);
        </script>
    """, unsafe_allow_html=True)


def verificar_auth():
    """
    Verifica que el usuario esté autenticado.
    Si no lo está, muestra mensaje y detiene la página.
    Llama esta función en cada página después de aplicar_estilos().

    Retorna: (user_id, nombre_negocio) si está autenticado.
    """
    if "auth" not in st.session_state:
        st.session_state.auth = {
            "logged": False,
            "user_id": None,
            "nombre_negocio": None,
            "email": None,
            "token": None,
        }

    if not st.session_state.auth["logged"]:
        st.warning("Debes iniciar sesión en la página principal para acceder a este módulo.")
        st.stop()

    return (
        st.session_state.auth["user_id"],
        st.session_state.auth["nombre_negocio"]
    )
