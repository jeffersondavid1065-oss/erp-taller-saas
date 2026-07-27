import streamlit as st
from sqlalchemy import create_engine, text
import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "erp_taller.db")

@st.cache_resource
def obtener_conexion():
    try:
        db_url = st.secrets["postgres"]["url"]
        engine = create_engine(db_url)
    except Exception:
        engine = create_engine(f"sqlite:///{LOCAL_DB_PATH}")
    
    return engine

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
            # ==========================================
            # NUEVAS TABLAS PARA EL MÓDULO DE ACEITES (SQLITE)
            # ==========================================
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
            # ==========================================
            # NUEVAS TABLAS PARA EL MÓDULO DE ACEITES (POSTGRESQL)
            # ==========================================
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
