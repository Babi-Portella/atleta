from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

class AthleteDB(Base):
    __tablename__ = "athletes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    age = Column(Integer)
    sport = Column(String(100))

class MeasurementDB(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    athlete_id = Column(Integer, ForeignKey("athletes.id"))
    sessao = Column(String(50))
    bpm = Column(Integer)
    duracao_s = Column(Integer)
    passos = Column(Integer)
    distancia_km = Column(Float)
    calorias_kcal = Column(Float)
    ritmo_min_km = Column(Float)

    accel_x = Column(Float)
    accel_y = Column(Float)
    accel_z = Column(Float)

    latitude = Column(Float)
    longitude = Column(Float)

    gps = Column(String(50))
    wifi = Column(String(50))


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Athlete Monitor API",
    description="API para monitoramento de atletas com ESP32",
    version="1.0.0"
)


# Dados enviados pelo ESP32
class Measurement(BaseModel):
    athlete_id: int
    sessao: str
    bpm: int
    duracao_s: int
    passos: int
    distancia_km: float
    calorias_kcal: float
    ritmo_min_km: float
    accel_g: List[float]
    latitude: float
    longitude: float
    gps: str
    wifi: str

class Athlete(BaseModel):
    name: str
    age: int
    sport: str

@app.get("/")
def root():
    return {
        "message": "Athlete Monitor API funcionando!"
    }

@app.post("/athletes")
def create_athlete(athlete: Athlete):

    db = SessionLocal()

    try:
        novo_atleta = AthleteDB(
            name=athlete.name,
            age=athlete.age,
            sport=athlete.sport
        )

        db.add(novo_atleta)
        db.commit()
        db.refresh(novo_atleta)

        return {
            "message": "Atleta criado com sucesso!",
            "id": novo_atleta.id
        }

    finally:
        db.close()

@app.post("/measurements")
def receive_measurement(measurement: Measurement):

    db = SessionLocal()

    try:
        nova_medicao = MeasurementDB(
            athlete_id=measurement.athlete_id,
            sessao=measurement.sessao,
            bpm=measurement.bpm,
            duracao_s=measurement.duracao_s,
            passos=measurement.passos,
            distancia_km=measurement.distancia_km,
            calorias_kcal=measurement.calorias_kcal,
            ritmo_min_km=measurement.ritmo_min_km,

            accel_x=measurement.accel_g[0],
            accel_y=measurement.accel_g[1],
            accel_z=measurement.accel_g[2],

            latitude=measurement.latitude,
            longitude=measurement.longitude,
            gps=measurement.gps,
            wifi=measurement.wifi
        )

        db.add(nova_medicao)
        db.commit()
        db.refresh(nova_medicao)

        return {
            "message": "Medição salva com sucesso!",
            "id": nova_medicao.id
        }

    finally:
        db.close()


@app.get("/measurements")
def get_measurements():

    db = SessionLocal()

    try:
        medicoes = db.query(MeasurementDB).all()

        return medicoes

    finally:
        db.close()


@app.get("/athletes/{athlete_id}/measurements")
def get_athlete_measurements(athlete_id: int):

    db = SessionLocal()

    try:
        medicoes = (
            db.query(MeasurementDB)
            .filter(MeasurementDB.athlete_id == athlete_id)
            .all()
        )

        return medicoes

    finally:
        db.close()