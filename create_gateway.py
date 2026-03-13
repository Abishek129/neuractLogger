#!/usr/bin/env python3
"""
Script to create a new gateway via the API.
Run this from your machine where you're authenticated.
"""
import requests

# API endpoint
API_URL = "http://127.0.0.1:5175"

# Gateway data
gateway_data = {
    "name": "Solar Factory Gateway",
    "host": "192.168.1.20",
    "ports": [5020],
    "protocol_hint": "modbus"
}

# Create the gateway
response = requests.post(
    f"{API_URL}/networking/gateways",
    json=gateway_data
)

if response.ok:
    print("✅ Gateway created successfully!")
    print(f"Response: {response.json()}")
else:
    print(f"❌ Error: {response.status_code}")
    print(f"Details: {response.text}")
