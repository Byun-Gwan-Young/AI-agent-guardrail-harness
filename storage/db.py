import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


# 프로젝트 루트에 있는 .env 파일을 불러옴
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)


def get_connection():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )