import requests
from .client import login, get_headers, BASE_URL


def fetch_latest_devices(type=1):
    token = login(type=type)
    headers = get_headers(token)

    url = f"{BASE_URL}/devices/latest"

    response = requests.post(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.text}")

    return response.json()


def fetch_device_history(device_name, type=1):
    token = login(type=type)
    headers = get_headers(token)

    url = f"{BASE_URL}/device/data"

    payload = {"deviceName": device_name}

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Error: {response.text}")

    return response.json()
