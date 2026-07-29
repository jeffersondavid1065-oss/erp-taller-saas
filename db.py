import streamlit as st
from sqlalchemy import create_engine, text
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")


@st.cache_resource
def obtener_conexion():
    """
    Crea el engine de SQLAlchemy UNA sola vez por proceso de servidor
    (cache_resource no serializa, mantiene el objeto vivo en memoria).

    NOTA IMPORTANTE PARA MÚLTIPLES TALLERES CONCURRENTES:
    Verifica que st.secrets["postgres"]["url"] apunte al *connection pooler*
    de Supabase (Supavisor, puerto 6543, modo "Transaction"), NO a la
    conexión directa (puerto 5432). La conexión directa tiene un límite de
    conexiones simultáneas mucho más bajo y se agota rápido con varios
    talleres usando la app al mismo tiempo. La URL del pooler se ve así:
        postgresql://usuario:password@HOST.pooler.supabase.com:6543/postgres
    """
    try:
        db_url = st.secrets["postgres"]["url"]
        engine = create_engine(
            db_url,
            pool_size=10,          # antes 5: más margen para varios talleres a la vez
            max_overflow=20,       # antes 10
            pool_pre_ping=True,
            pool_recycle=300,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        st.warning(
            f"⚠️ No se pudo conectar a Postgres/Supabase, usando base local de respaldo. "
            f"Detalle: {e}"
        )
        engine = create_engine(f"sqlite:///{LOCAL_DB_PATH}")

    return engine


@st.cache_resource
def init_db():
    """
    Crea las tablas si no existen. Cacheada con cache_resource para que
    se ejecute UNA sola vez por proceso de servidor, no en cada rerun.
    Si cambias el esquema, reinicia la app (o usa init_db.clear() manualmente
    desde una página de administración) para forzar que corra de nuevo.
    """
    engine = obtener_conexion()
    is_sqlite = "sqlite" in str(engine.url)

    with engine.begin() as conn:
        if is_sqlite:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_taller TEXT NOT NULL,
                    nombre_dueno TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    estado_suscripcion TEXT DEFAULT 'Activo',
                    codigo_verificacion TEXT,
                    activo BOOLEAN DEFAULT 0,
                    fecha_pago_limite DATE,
                    token_sesion TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Empresas_Clientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER,
                    razon_social TEXT NOT NULL,
                    nit TEXT NOT NULL,
                    telefono TEXT,
                    email TEXT
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Mecanicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER,
                    nombre TEXT NOT NULL,
                    documento TEXT NOT NULL,
                    estado TEXT DEFAULT 'Activo'
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Hojas_Trabajo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER,
                    placa TEXT NOT NULL,
                    empresa_id INTEGER,
                    fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT NOT NULL
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Detalles_Orden (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hoja_id INTEGER,
                    tipo_item TEXT CHECK(tipo_item IN ('Mano de Obra', 'Repuesto')),
                    descripcion TEXT NOT NULL,
                    mecanico_id INTEGER,
                    costo_compra REAL DEFAULT 0,
                    precio_venta REAL NOT NULL,
                    comision_mecanico REAL DEFAULT 0
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Inventario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    nombre_producto TEXT NOT NULL,
                    codigo_ref TEXT,
                    stock_actual INTEGER NOT NULL DEFAULT 0,
                    stock_minimo INTEGER NOT NULL DEFAULT 2,
                    costo_compra REAL DEFAULT 0,
                    precio_venta REAL NOT NULL DEFAULT 0
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Vehiculos_Flota (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    empresa_id INTEGER NOT NULL,
                    placa TEXT NOT NULL,
                    modelo_vehiculo TEXT,
                    fecha_ultimo_servicio DATE,
                    fecha_proximo_servicio DATE,
                    kilometraje_actual INTEGER DEFAULT 0,
                    intervalo_meses INTEGER DEFAULT 3
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Recetas_Vehiculo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vehiculo_id INTEGER NOT NULL,
                    inventario_id INTEGER NOT NULL,
                    cantidad INTEGER DEFAULT 1,
                    FOREIGN KEY (vehiculo_id) REFERENCES Vehiculos_Flota(id) ON DELETE CASCADE,
                    FOREIGN KEY (inventario_id) REFERENCES Inventario(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Categorias_Gasto (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    tipo TEXT CHECK(tipo IN ('Fijo', 'Variable')) DEFAULT 'Variable',
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Gastos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    categoria_id INTEGER NOT NULL,
                    descripcion TEXT NOT NULL,
                    monto REAL NOT NULL,
                    fecha DATE NOT NULL,
                    tipo TEXT CHECK(tipo IN ('Fijo', 'Variable')) DEFAULT 'Variable',
                    comprobante_url TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (categoria_id) REFERENCES Categorias_Gasto(id) ON DELETE RESTRICT
                )
            '''))
        else:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Usuarios (
                    id SERIAL PRIMARY KEY,
                    nombre_taller TEXT NOT NULL,
                    nombre_dueno TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    estado_suscripcion TEXT DEFAULT 'Activo',
                    codigo_verificacion TEXT,
                    activo BOOLEAN DEFAULT FALSE,
                    fecha_pago_limite DATE,
                    token_sesion VARCHAR(255),
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Empresas_Clientes (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER,
                    razon_social TEXT NOT NULL,
                    nit TEXT NOT NULL,
                    telefono TEXT,
                    email TEXT
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Mecanicos (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER,
                    nombre TEXT NOT NULL,
                    documento TEXT NOT NULL,
                    estado TEXT DEFAULT 'Activo'
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Hojas_Trabajo (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER,
                    placa TEXT NOT NULL,
                    empresa_id INTEGER,
                    fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT NOT NULL
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Detalles_Orden (
                    id SERIAL PRIMARY KEY,
                    hoja_id INTEGER,
                    tipo_item TEXT CHECK(tipo_item IN ('Mano de Obra', 'Repuesto')),
                    descripcion TEXT NOT NULL,
                    mecanico_id INTEGER,
                    costo_compra REAL DEFAULT 0,
                    precio_venta REAL NOT NULL,
                    comision_mecanico REAL DEFAULT 0
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Inventario (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    nombre_producto VARCHAR(255) NOT NULL,
                    codigo_ref VARCHAR(100),
                    stock_actual INTEGER NOT NULL DEFAULT 0,
                    stock_minimo INTEGER NOT NULL DEFAULT 2,
                    costo_compra NUMERIC(12, 2) NOT NULL DEFAULT 0,
                    precio_venta NUMERIC(12, 2) NOT NULL DEFAULT 0,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Vehiculos_Flota (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    empresa_id INTEGER NOT NULL,
                    placa VARCHAR(50) NOT NULL,
                    modelo_vehiculo VARCHAR(255),
                    fecha_ultimo_servicio DATE,
                    fecha_proximo_servicio DATE,
                    kilometraje_actual INTEGER DEFAULT 0,
                    intervalo_meses INTEGER DEFAULT 3,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (empresa_id) REFERENCES Empresas_Clientes(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Recetas_Vehiculo (
                    id SERIAL PRIMARY KEY,
                    vehiculo_id INTEGER NOT NULL,
                    inventario_id INTEGER NOT NULL,
                    cantidad INTEGER DEFAULT 1,
                    FOREIGN KEY (vehiculo_id) REFERENCES Vehiculos_Flota(id) ON DELETE CASCADE,
                    FOREIGN KEY (inventario_id) REFERENCES Inventario(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Categorias_Gasto (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    nombre VARCHAR(100) NOT NULL,
                    descripcion TEXT,
                    tipo VARCHAR(20) CHECK(tipo IN ('Fijo', 'Variable')) DEFAULT 'Variable',
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Gastos (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    categoria_id INTEGER NOT NULL,
                    descripcion TEXT NOT NULL,
                    monto NUMERIC(12, 2) NOT NULL,
                    fecha DATE NOT NULL,
                    tipo VARCHAR(20) CHECK(tipo IN ('Fijo', 'Variable')) DEFAULT 'Variable',
                    comprobante_url TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (categoria_id) REFERENCES Categorias_Gasto(id) ON DELETE RESTRICT
                )
            '''))

        # ==========================================
        # ÍNDICES: mismas sentencias para SQLite y Postgres.
        # Sin esto, cada consulta filtrada por usuario_id hace un recorrido
        # completo de la tabla. Con varios talleres compartiendo las mismas
        # tablas, esto se vuelve más lento para TODOS a medida que crece el
        # historial combinado, aunque cada taller solo pida sus propios datos.
        # ==========================================
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hojas_trabajo_usuario ON Hojas_Trabajo(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hojas_trabajo_usuario_estado ON Hojas_Trabajo(usuario_id, estado)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_detalles_orden_hoja ON Detalles_Orden(hoja_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_inventario_usuario ON Inventario(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_empresas_usuario ON Empresas_Clientes(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_mecanicos_usuario ON Mecanicos(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_vehiculos_flota_usuario ON Vehiculos_Flota(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_recetas_vehiculo_vid ON Recetas_Vehiculo(vehiculo_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gastos_usuario ON Gastos(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gastos_usuario_fecha ON Gastos(usuario_id, fecha)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_categorias_gasto_usuario ON Categorias_Gasto(usuario_id)"))
        
        # Agregar columna token_sesion si no existe (para persistencia de sesión)
        try:
            if is_sqlite:
                # SQLite: verificar si la columna existe
                resultado = conn.execute(text("PRAGMA table_info(Usuarios)")).fetchall()
                columnas = [col[1] for col in resultado]
                if 'token_sesion' not in columnas:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN token_sesion TEXT"))
            else:
                # Postgres: intentar agregar, si ya existe no falla
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS token_sesion VARCHAR(255)"))
            
            # Crear índice para búsquedas rápidas de token
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_usuarios_token ON Usuarios(token_sesion)"))
        except Exception as e:
            # Si falla, probablemente la columna ya existe o hay otro problema
            # No es crítico, la app funciona igual
            pass

    return True
