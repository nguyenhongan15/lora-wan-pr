import requests
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL")
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
EMAIL2 = os.getenv("EMAIL2")
PASSWORD2 = os.getenv("PASSWORD2")


def login(type=1):
    url = f"{BASE_URL}/login"

    if type == 2:
        payload = {"email": EMAIL2, "password": PASSWORD2}
    else:
        payload = {"email": EMAIL, "password": PASSWORD}

    response = requests.post(url, json=payload)

    if response.status_code != 200:
        raise Exception(f"Login failed: {response.text}")

    token = response.json()["token"]
    return token


def get_headers(token):
    return {"Authorization": f"Bearer {token}"}
