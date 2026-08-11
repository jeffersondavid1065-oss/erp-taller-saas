import streamlit as st
from sqlalchemy import create_engine, text
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")


@st.cache_resource
def obtener_conexion():
    try:
        db_url = st.secrets["postgres"]["url"]
        engine = create_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
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


def mensaje_error_amigable(e, accion="completar la acción"):
    """Traduce una excepción cruda de BD/red a un mensaje que un usuario sin
    conocimientos técnicos pueda entender, en vez de mostrarle la traza de
    Python/SQL tal cual. `accion` describe en pocas palabras qué se intentaba
    hacer (ej. "eliminar el mecánico"), para que el mensaje sea específico."""
    texto = str(e).lower()
    if "unique" in texto or "duplicate" in texto:
        return "Ya existe un registro con ese mismo dato (posible duplicado). Verifica e intenta de nuevo."
    if "foreign key" in texto or "violates foreign key" in texto or "referenced" in texto:
        return "No se pudo completar porque hay otra información del sistema relacionada con esto."
    if "not null" in texto or "null value" in texto:
        return "Falta completar un campo obligatorio."
    if "timeout" in texto or "connection" in texto or "operationalerror" in texto or "could not connect" in texto:
        return "No se pudo conectar con la base de datos. Revisa tu conexión a internet e intenta de nuevo en unos segundos."
    return f"No se pudo {accion}. Intenta de nuevo en unos segundos; si el problema sigue, contacta a soporte."


@st.cache_resource
def init_db():
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
                    logo_path TEXT,
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
                    email TEXT,
                    tipo_documento TEXT DEFAULT 'NIT',
                    alegra_contact_id TEXT,
                    digito_verificacion TEXT,
                    regimen TEXT DEFAULT 'SIMPLIFIED_REGIME'
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
                    numero_orden INTEGER,
                    placa TEXT NOT NULL,
                    empresa_id INTEGER,
                    fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT NOT NULL
                )
            '''))
            # --- NUEVO: contador de número de orden independiente por taller ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Contadores_Orden (
                    usuario_id INTEGER PRIMARY KEY,
                    ultimo_numero INTEGER NOT NULL DEFAULT 0
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
                    stock_actual REAL NOT NULL DEFAULT 0,
                    stock_minimo REAL NOT NULL DEFAULT 2,
                    costo_compra REAL DEFAULT 0,
                    precio_venta REAL NOT NULL DEFAULT 0,
                    unidad_medida TEXT DEFAULT 'Unidad'
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
            # --- NUEVO: Operarios de Patio (rol restringido a Recepción) ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Operarios_Patio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    nombre_operario TEXT NOT NULL,
                    usuario_login TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    token_sesion TEXT,
                    activo BOOLEAN DEFAULT 1,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE
                )
            '''))
            # --- NUEVO: Cartera (abonos sobre órdenes facturadas a crédito) ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Abonos_Taller (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    hoja_id INTEGER NOT NULL,
                    monto REAL NOT NULL DEFAULT 0,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notas TEXT,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (hoja_id) REFERENCES Hojas_Trabajo(id) ON DELETE CASCADE
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
                    logo_path TEXT,
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
                    email TEXT,
                    tipo_documento VARCHAR(10) DEFAULT 'NIT',
                    alegra_contact_id TEXT,
                    digito_verificacion VARCHAR(5),
                    regimen VARCHAR(20) DEFAULT 'SIMPLIFIED_REGIME'
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
                    numero_orden INTEGER,
                    placa TEXT NOT NULL,
                    empresa_id INTEGER,
                    fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    estado TEXT NOT NULL
                )
            '''))
            # --- NUEVO: contador de número de orden independiente por taller ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Contadores_Orden (
                    usuario_id INTEGER PRIMARY KEY,
                    ultimo_numero INTEGER NOT NULL DEFAULT 0
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
                    stock_actual NUMERIC(12,3) NOT NULL DEFAULT 0,
                    stock_minimo NUMERIC(12,3) NOT NULL DEFAULT 2,
                    costo_compra NUMERIC(12,2) NOT NULL DEFAULT 0,
                    precio_venta NUMERIC(12,2) NOT NULL DEFAULT 0,
                    unidad_medida VARCHAR(20) DEFAULT 'Unidad',
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
                    monto NUMERIC(12,2) NOT NULL,
                    fecha DATE NOT NULL,
                    tipo VARCHAR(20) CHECK(tipo IN ('Fijo', 'Variable')) DEFAULT 'Variable',
                    comprobante_url TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (categoria_id) REFERENCES Categorias_Gasto(id) ON DELETE RESTRICT
                )
            '''))
            # --- NUEVO: Operarios de Patio (rol restringido a Recepción) ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Operarios_Patio (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    nombre_operario VARCHAR(255) NOT NULL,
                    usuario_login VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    token_sesion VARCHAR(255),
                    activo BOOLEAN DEFAULT TRUE,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE
                )
            '''))
            # --- NUEVO: Cartera (abonos sobre órdenes facturadas a crédito) ---
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS Abonos_Taller (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL,
                    hoja_id INTEGER NOT NULL,
                    monto NUMERIC(12,2) NOT NULL DEFAULT 0,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notas TEXT,
                    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (hoja_id) REFERENCES Hojas_Trabajo(id) ON DELETE CASCADE
                )
            '''))

        # ==========================================
        # ÍNDICES
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
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_operarios_patio_usuario ON Operarios_Patio(usuario_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_operarios_patio_login ON Operarios_Patio(usuario_login)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_operarios_patio_token ON Operarios_Patio(token_sesion)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_abonos_taller_hoja ON Abonos_Taller(hoja_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_abonos_taller_usuario ON Abonos_Taller(usuario_id)"))

        # ==========================================
        # MIGRACIONES SEGURAS
        # ==========================================
        try:
            if is_sqlite:
                cols_u = [c[1] for c in conn.execute(text("PRAGMA table_info(Usuarios)")).fetchall()]
                cols_i = [c[1] for c in conn.execute(text("PRAGMA table_info(Inventario)")).fetchall()]
                cols_do = [c[1] for c in conn.execute(text("PRAGMA table_info(Detalles_Orden)")).fetchall()]
                cols_ht = [c[1] for c in conn.execute(text("PRAGMA table_info(Hojas_Trabajo)")).fetchall()]
                cols_ec = [c[1] for c in conn.execute(text("PRAGMA table_info(Empresas_Clientes)")).fetchall()]

                if 'token_sesion' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN token_sesion TEXT"))
                if 'logo_path' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN logo_path TEXT"))
                # --- NUEVO: config de IVA del taller ---
                if 'iva_activo' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_activo BOOLEAN DEFAULT 0"))
                if 'iva_porcentaje' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_porcentaje REAL DEFAULT 19.0"))
                if 'iva_incluido' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_incluido BOOLEAN DEFAULT 0"))
                # --- NUEVO: default de tipo de IVA por categoría (catálogo, no booleano) ---
                if 'iva_aplica_mano_obra' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_aplica_mano_obra BOOLEAN DEFAULT 1"))
                if 'iva_aplica_repuestos' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_aplica_repuestos BOOLEAN DEFAULT 1"))
                if 'iva_tipo_default_mano_obra' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_tipo_default_mano_obra TEXT DEFAULT 'IVA 19%'"))
                if 'iva_tipo_default_repuestos' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN iva_tipo_default_repuestos TEXT DEFAULT 'IVA 19%'"))

                if 'unidad_medida' not in cols_i:
                    conn.execute(text("ALTER TABLE Inventario ADD COLUMN unidad_medida TEXT DEFAULT 'Unidad'"))
                # --- NUEVO (legado): excepción booleana de IVA por producto ---
                if 'aplica_iva' not in cols_i:
                    conn.execute(text("ALTER TABLE Inventario ADD COLUMN aplica_iva BOOLEAN"))
                # --- NUEVO: tipo de IVA por producto (catálogo: Excluido, IVA 5%, IVA 19%, etc.) ---
                if 'iva_tipo' not in cols_i:
                    conn.execute(text("ALTER TABLE Inventario ADD COLUMN iva_tipo TEXT"))

                # --- NUEVO (legado): excepción booleana de IVA por ítem de orden ---
                if 'aplica_iva' not in cols_do:
                    conn.execute(text("ALTER TABLE Detalles_Orden ADD COLUMN aplica_iva BOOLEAN"))
                # --- NUEVO: tipo de IVA por ítem de orden (catálogo) ---
                if 'iva_tipo' not in cols_do:
                    conn.execute(text("ALTER TABLE Detalles_Orden ADD COLUMN iva_tipo TEXT"))

                # --- NUEVO: trazabilidad de quién recepcionó (operario de patio) ---
                if 'creado_por_operario_id' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN creado_por_operario_id INTEGER"))
                # stock_actual a REAL para soportar decimales (kg, metros, etc)
                # SQLite no soporta ALTER COLUMN, pero REAL ya acepta decimales

                # --- NUEVO: facturación electrónica (Alegra), por taller ---
                if 'alegra_email' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN alegra_email TEXT"))
                if 'alegra_token' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN alegra_token TEXT"))
                if 'fe_habilitada' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN fe_habilitada BOOLEAN DEFAULT 0"))
                # --- NUEVO: tipo de documento e id de contacto en Alegra, por cliente ---
                if 'tipo_documento' not in cols_ec:
                    conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN tipo_documento TEXT DEFAULT 'NIT'"))
                if 'alegra_contact_id' not in cols_ec:
                    conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN alegra_contact_id TEXT"))
                # --- NUEVO: datos del RUT usados para facturar electrónicamente ---
                if 'digito_verificacion' not in cols_ec:
                    conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN digito_verificacion TEXT"))
                if 'regimen' not in cols_ec:
                    conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN regimen TEXT DEFAULT 'SIMPLIFIED_REGIME'"))
                # --- NUEVO: facturación electrónica y método de pago, por orden ---
                if 'tipo_pago' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN tipo_pago TEXT"))
                if 'fecha_vencimiento_credito' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN fecha_vencimiento_credito DATE"))
                if 'factura_alegra_id' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_alegra_id TEXT"))
                if 'factura_cufe' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_cufe TEXT"))
                if 'factura_pdf_url' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_pdf_url TEXT"))
                if 'factura_xml_url' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_xml_url TEXT"))
                if 'factura_estado' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_estado TEXT"))
                if 'factura_prefijo' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_prefijo TEXT"))
                if 'factura_numero' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN factura_numero TEXT"))
                if 'nota_credito_alegra_id' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_alegra_id TEXT"))
                if 'nota_credito_pdf_url' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_pdf_url TEXT"))
                if 'nota_credito_xml_url' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_xml_url TEXT"))
                if 'nota_credito_prefijo' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_prefijo TEXT"))
                if 'nota_credito_numero' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_numero TEXT"))
                if 'nota_credito_fecha' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN nota_credito_fecha TIMESTAMP"))
                # --- NUEVO: Cartera (saldo pendiente de órdenes facturadas a crédito) ---
                if 'saldo_pendiente' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN saldo_pendiente REAL"))
                # --- NUEVO: numeración de orden independiente por taller (antes se
                # mostraba el id autoincremental global, compartido entre todas las
                # cuentas). Al agregar la columna, se numeran retroactivamente las
                # órdenes ya existentes (1, 2, 3... por taller, en el orden en que
                # se crearon) y se deja el contador de cada taller listo para seguir
                # desde ahí con las órdenes nuevas.
                if 'numero_orden' not in cols_ht:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN numero_orden INTEGER"))
                    conn.execute(text('''
                        UPDATE Hojas_Trabajo
                        SET numero_orden = (
                            SELECT rn FROM (
                                SELECT id, ROW_NUMBER() OVER (PARTITION BY usuario_id ORDER BY id) as rn
                                FROM Hojas_Trabajo
                            ) sub
                            WHERE sub.id = Hojas_Trabajo.id
                        )
                        WHERE numero_orden IS NULL
                    '''))
                    conn.execute(text('''
                        INSERT INTO Contadores_Orden (usuario_id, ultimo_numero)
                        SELECT usuario_id, MAX(numero_orden) FROM Hojas_Trabajo
                        WHERE usuario_id IS NOT NULL
                        GROUP BY usuario_id
                        ON CONFLICT(usuario_id) DO UPDATE SET ultimo_numero = excluded.ultimo_numero
                    '''))
                # --- NUEVO: datos fiscales/contacto del taller, para que aparezcan en las
                # facturas en PDF sin depender de session_state (se perdían al recargar) ---
                if 'nit_taller' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN nit_taller TEXT"))
                if 'telefono_taller' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN telefono_taller TEXT"))
                if 'direccion_taller' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN direccion_taller TEXT"))
                if 'ciudad_taller' not in cols_u:
                    conn.execute(text("ALTER TABLE Usuarios ADD COLUMN ciudad_taller TEXT"))
                # --- FIX: Recepción guardaba 'En revision'/'En reparacion' (sin tilde)
                # mientras que el Tablero de Pendientes y Facturación e historial
                # esperan 'En revisión'/'En reparación' (con tilde) - las órdenes en
                # esos dos estados no coincidían con ninguna columna y desaparecían
                # del tablero. Se normaliza lo ya guardado; el selector de Recepción
                # ya quedó corregido para no volver a generar el desajuste.
                conn.execute(text("UPDATE Hojas_Trabajo SET estado = 'En revisión' WHERE estado = 'En revision'"))
                conn.execute(text("UPDATE Hojas_Trabajo SET estado = 'En reparación' WHERE estado = 'En reparacion'"))
            else:
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS token_sesion VARCHAR(255)"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS logo_path TEXT"))
                # --- NUEVO: config de IVA del taller ---
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_activo BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_porcentaje NUMERIC(5,2) DEFAULT 19.00"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_incluido BOOLEAN DEFAULT FALSE"))
                # --- NUEVO (legado): booleanos de categoría, ya no se usan en la UI pero se conservan ---
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_aplica_mano_obra BOOLEAN DEFAULT TRUE"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_aplica_repuestos BOOLEAN DEFAULT TRUE"))
                # --- NUEVO: default de tipo de IVA por categoría (catálogo: Excluido, IVA 5%, IVA 19%, etc.) ---
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_tipo_default_mano_obra VARCHAR(30) DEFAULT 'IVA 19%'"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS iva_tipo_default_repuestos VARCHAR(30) DEFAULT 'IVA 19%'"))

                conn.execute(text("ALTER TABLE Inventario ADD COLUMN IF NOT EXISTS unidad_medida VARCHAR(20) DEFAULT 'Unidad'"))
                # --- NUEVO (legado): excepción booleana de IVA por producto ---
                conn.execute(text("ALTER TABLE Inventario ADD COLUMN IF NOT EXISTS aplica_iva BOOLEAN"))
                # --- NUEVO: tipo de IVA por producto (catálogo) ---
                conn.execute(text("ALTER TABLE Inventario ADD COLUMN IF NOT EXISTS iva_tipo VARCHAR(30)"))
                # Cambiar stock_actual a NUMERIC con decimales para kg, metros, etc
                conn.execute(text("ALTER TABLE Inventario ALTER COLUMN stock_actual TYPE NUMERIC(12,3)"))
                conn.execute(text("ALTER TABLE Inventario ALTER COLUMN stock_minimo TYPE NUMERIC(12,3)"))

                # --- NUEVO (legado): excepción booleana de IVA por ítem de orden ---
                conn.execute(text("ALTER TABLE Detalles_Orden ADD COLUMN IF NOT EXISTS aplica_iva BOOLEAN"))
                # --- NUEVO: tipo de IVA por ítem de orden (catálogo) ---
                conn.execute(text("ALTER TABLE Detalles_Orden ADD COLUMN IF NOT EXISTS iva_tipo VARCHAR(30)"))

                # --- NUEVO: trazabilidad de quién recepcionó (operario de patio) ---
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS creado_por_operario_id INTEGER"))

                # --- NUEVO: facturación electrónica (Alegra), por taller ---
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS alegra_email TEXT"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS alegra_token TEXT"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS fe_habilitada BOOLEAN DEFAULT FALSE"))
                # --- NUEVO: tipo de documento e id de contacto en Alegra, por cliente ---
                conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN IF NOT EXISTS tipo_documento VARCHAR(10) DEFAULT 'NIT'"))
                conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN IF NOT EXISTS alegra_contact_id TEXT"))
                # --- NUEVO: datos del RUT usados para facturar electrónicamente ---
                conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN IF NOT EXISTS digito_verificacion VARCHAR(5)"))
                conn.execute(text("ALTER TABLE Empresas_Clientes ADD COLUMN IF NOT EXISTS regimen VARCHAR(20) DEFAULT 'SIMPLIFIED_REGIME'"))
                # --- NUEVO: facturación electrónica y método de pago, por orden ---
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS tipo_pago VARCHAR(20)"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS fecha_vencimiento_credito DATE"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_alegra_id TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_cufe TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_pdf_url TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_xml_url TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_estado TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_prefijo TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS factura_numero TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_alegra_id TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_pdf_url TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_xml_url TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_prefijo TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_numero TEXT"))
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS nota_credito_fecha TIMESTAMP"))
                # --- NUEVO: Cartera (saldo pendiente de órdenes facturadas a crédito) ---
                conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN IF NOT EXISTS saldo_pendiente NUMERIC(12,2)"))
                # --- NUEVO: numeración de orden independiente por taller (antes se
                # mostraba el id autoincremental global, compartido entre todas las
                # cuentas). Solo se hace el backfill una vez, la primera vez que la
                # columna no existe todavía, numerando retroactivamente las órdenes
                # existentes (1, 2, 3... por taller, en el orden en que se crearon)
                # y dejando el contador de cada taller listo para las órdenes nuevas.
                cols_ht_pg = [c[0] for c in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'hojas_trabajo'"
                )).fetchall()]
                if 'numero_orden' not in cols_ht_pg:
                    conn.execute(text("ALTER TABLE Hojas_Trabajo ADD COLUMN numero_orden INTEGER"))
                    conn.execute(text('''
                        UPDATE Hojas_Trabajo h
                        SET numero_orden = sub.rn
                        FROM (
                            SELECT id, ROW_NUMBER() OVER (PARTITION BY usuario_id ORDER BY id) as rn
                            FROM Hojas_Trabajo
                        ) sub
                        WHERE h.id = sub.id AND h.numero_orden IS NULL
                    '''))
                    conn.execute(text('''
                        INSERT INTO Contadores_Orden (usuario_id, ultimo_numero)
                        SELECT usuario_id, MAX(numero_orden) FROM Hojas_Trabajo
                        WHERE usuario_id IS NOT NULL
                        GROUP BY usuario_id
                        ON CONFLICT (usuario_id) DO UPDATE SET ultimo_numero = excluded.ultimo_numero
                    '''))
                # --- NUEVO: datos fiscales/contacto del taller, para que aparezcan en las
                # facturas en PDF sin depender de session_state (se perdían al recargar) ---
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS nit_taller TEXT"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS telefono_taller TEXT"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS direccion_taller TEXT"))
                conn.execute(text("ALTER TABLE Usuarios ADD COLUMN IF NOT EXISTS ciudad_taller TEXT"))
                # --- FIX: Recepción guardaba 'En revision'/'En reparacion' (sin tilde)
                # mientras que el Tablero de Pendientes y Facturación e historial
                # esperan 'En revisión'/'En reparación' (con tilde) - las órdenes en
                # esos dos estados no coincidían con ninguna columna y desaparecían
                # del tablero. Se normaliza lo ya guardado; el selector de Recepción
                # ya quedó corregido para no volver a generar el desajuste.
                conn.execute(text("UPDATE Hojas_Trabajo SET estado = 'En revisión' WHERE estado = 'En revision'"))
                conn.execute(text("UPDATE Hojas_Trabajo SET estado = 'En reparación' WHERE estado = 'En reparacion'"))

            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_usuarios_token ON Usuarios(token_sesion)"))
        except Exception:
            pass

    return True
