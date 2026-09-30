"""
Seeding script to register the Motor AAS and its submodels into:
1. Eclipse BaSyx v2 AAS Environment (Port 8081)
2. Eclipse BaSyx v2 Submodel Registry (Port 8082)
3. Eclipse BaSyx v2 AAS Registry (Port 8080)
"""

import base64
import json
import os
import sys
import time
import requests

# Service URLs for BaSyx v2 Architecture
BASYX_AAS_REGISTRY_URL = os.getenv("BASYX_AAS_REGISTRY_URL", "http://localhost:8080")
BASYX_ENV_URL = os.getenv("BASYX_ENV_URL", "http://localhost:8081")
BASYX_SM_REGISTRY_URL = os.getenv("BASYX_SM_REGISTRY_URL", "http://localhost:8082")


def base64_url_encode(string_id: str) -> str:
    """Encodes string ID to Base64 URL-safe format without padding per AAS v3 specs."""
    return base64.urlsafe_b64encode(string_id.encode("utf-8")).decode("utf-8").rstrip("=")


def find_config_file() -> str:
    """Locates 'motor_aas_definition.json' across standard relative paths."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "../config/motor_aas_definition.json"),
        os.path.join(script_dir, "config/motor_aas_definition.json"),
        os.path.join(script_dir, "motor_aas_definition.json"),
        os.path.join(os.getcwd(), "config/motor_aas_definition.json"),
        os.path.join(os.getcwd(), "motor_aas_definition.json"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)

    raise FileNotFoundError(
        "[Error] Could not locate 'motor_aas_definition.json'. Searched paths:\n"
        + "\n".join(f"  - {p}" for p in candidates)
    )


def verify_services():
    """Verifies HTTP accessibility for all three BaSyx endpoints."""
    services = {
        "AAS Registry (8080)": f"{BASYX_AAS_REGISTRY_URL}/shell-descriptors",
        "AAS Environment (8081)": f"{BASYX_ENV_URL}/shells",
        "Submodel Registry (8082)": f"{BASYX_SM_REGISTRY_URL}/submodel-descriptors",
    }
    
    print("[BaSyx Seeder] Verifying service connectivity...")
    all_ok = True
    for name, url in services.items():
        try:
            r = requests.get(url, timeout=3)
            print(f"  ✓ {name}: Reachable (Status {r.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"  ✗ {name}: UNREACHABLE at {url} ({e})")
            all_ok = False
            
    if not all_ok:
        print("[Warning] Some BaSyx services are unreachable. Ensure Docker containers are running.")


def seed_basyx():
    print("=========================================================================")
    print("      Eclipse BaSyx v2 Tri-Service Asset Administration Shell Seeder     ")
    print("=========================================================================\n")

    verify_services()

    try:
        json_path = find_config_file()
        print(f"\n[BaSyx Seeder] Loading definition from: {json_path}")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Fatal] {e}")
        sys.exit(1)

    submodels = data.get("submodels", [])
    aas_id = data.get("id", "urn:motor:aas:digitaltwin")
    aas_id_short = data.get("idShort", "MotorDigitalTwin_AAS")

    submodel_descriptors = []

    # ---------------------------------------------------------
    # 1. Register Submodels in Environment & Submodel Registry
    # ---------------------------------------------------------
    print("\n--- Phase 1: Registering Submodels ---")
    for sm in submodels:
        sm_id = sm.get("id")
        sm_id_short = sm.get("idShort")
        sm_id_b64 = base64_url_encode(sm_id)

        # A. Environment (Port 8081)
        sm_payload = {
            "id": sm_id,
            "idShort": sm_id_short,
            "modelType": "Submodel",
            "submodelElements": sm.get("submodelElements", []),
        }

        try:
            res = requests.post(f"{BASYX_ENV_URL}/submodels", json=sm_payload, timeout=5)
            if res.status_code in [200, 201]:
                print(f"  [Env 8081] Created Submodel: '{sm_id_short}'")
            elif res.status_code in [409, 400] and "already exists" in res.text.lower():
                print(f"  [Env 8081] Submodel already exists: '{sm_id_short}'")
            else:
                print(f"  [Env 8081 Warning] Submodel '{sm_id_short}' ({res.status_code}): {res.text[:100]}")
        except Exception as e:
            print(f"  [Env 8081 Error] Failed to register Submodel '{sm_id_short}': {e}")

        # B. Submodel Registry (Port 8082)
        sm_descriptor = {
            "id": sm_id,
            "idShort": sm_id_short,
            "endpoints": [
                {
                    "interface": "SUBMODEL-3.0",
                    "protocolInformation": {
                        "href": f"{BASYX_ENV_URL}/submodels/{sm_id_b64}",
                        "endpointProtocol": "http",
                    },
                }
            ],
        }
        submodel_descriptors.append(sm_descriptor)

        try:
            res = requests.post(
                f"{BASYX_SM_REGISTRY_URL}/submodel-descriptors",
                json=sm_descriptor,
                timeout=5,
            )
            if res.status_code in [200, 201]:
                print(f"  [Registry 8082] Created SM Descriptor: '{sm_id_short}'")
            elif res.status_code in [409, 400] and "already exists" in res.text.lower():
                print(f"  [Registry 8082] SM Descriptor already exists: '{sm_id_short}'")
            else:
                print(f"  [Registry 8082 Warning] SM Descriptor '{sm_id_short}' ({res.status_code}): {res.text[:100]}")
        except Exception as e:
            print(f"  [Registry 8082 Error] Failed to register SM Descriptor '{sm_id_short}': {e}")

    # ---------------------------------------------------------
    # 2. Register AAS Shell in Environment & AAS Registry
    # ---------------------------------------------------------
    print("\n--- Phase 2: Registering Asset Administration Shell ---")
    submodel_references = [
        {"type": "ModelReference", "keys": [{"type": "Submodel", "value": sm.get("id")}]}
        for sm in submodels
    ]

    # A. Environment (Port 8081)
    shell_payload = {
        "id": aas_id,
        "idShort": aas_id_short,
        "assetInformation": data.get("assetInformation", {"assetKind": "Instance", "globalAssetId": "urn:motor:asset:001"}),
        "submodels": submodel_references,
    }

    try:
        res = requests.post(f"{BASYX_ENV_URL}/shells", json=shell_payload, timeout=5)
        if res.status_code in [200, 201]:
            print(f"  [Env 8081] Created AAS Shell: '{aas_id_short}'")
        elif res.status_code in [409, 400] and "already exists" in res.text.lower():
            print(f"  [Env 8081] AAS Shell already exists: '{aas_id_short}'")
        else:
            print(f"  [Env 8081 Warning] Shell '{aas_id_short}' ({res.status_code}): {res.text[:100]}")
    except Exception as e:
        print(f"  [Env 8081 Error] Failed to register Shell '{aas_id_short}': {e}")

    # B. AAS Registry (Port 8080)
    aas_id_b64 = base64_url_encode(aas_id)
    shell_descriptor = {
        "id": aas_id,
        "idShort": aas_id_short,
        "endpoints": [
            {
                "interface": "AAS-3.0",
                "protocolInformation": {
                    "href": f"{BASYX_ENV_URL}/shells/{aas_id_b64}",
                    "endpointProtocol": "http",
                },
            }
        ],
        "submodelDescriptors": submodel_descriptors,
    }

    try:
        res = requests.post(
            f"{BASYX_AAS_REGISTRY_URL}/shell-descriptors",
            json=shell_descriptor,
            timeout=5,
        )
        if res.status_code in [200, 201]:
            print(f"  [Registry 8080] Created AAS Descriptor: '{aas_id_short}'")
        elif res.status_code in [409, 400] and "already exists" in res.text.lower():
            print(f"  [Registry 8080] AAS Descriptor already exists: '{aas_id_short}'")
        else:
            print(f"  [Registry 8080 Warning] AAS Descriptor '{aas_id_short}' ({res.status_code}): {res.text[:100]}")
    except Exception as e:
        print(f"  [Registry 8080 Error] Failed to register AAS Descriptor '{aas_id_short}': {e}")

    print("\n=========================================================================")
    print(" [BaSyx Seeder] Seeding process completed successfully.")
    print("=========================================================================\n")


if __name__ == "__main__":
    seed_basyx()