"""
Ejecutar UNA SOLA VEZ en tu máquina para obtener el refresh token.
Requiere: pip install msal
"""

import msal
import json

CLIENT_ID = "435db4d4-878b-4cf5-a404-a95f22a15cd5"
TENANT_ID = "7cde64aa-56ff-4bad-814f-85d33e9a5de1"

SCOPES = [
    "https://analysis.windows.net/powerbi/api/Report.Read.All",
    "https://analysis.windows.net/powerbi/api/Dashboard.Read.All",
    "https://analysis.windows.net/powerbi/api/Workspace.Read.All",
    "https://analysis.windows.net/powerbi/api/Tenant.Read.All",
]

app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
)

flow = app.initiate_device_flow(scopes=SCOPES)
if "user_code" not in flow:
    raise ValueError(f"Error iniciando device flow: {flow}")

print("\n" + "="*60)
print(flow["message"])
print("="*60 + "\n")

result = app.acquire_token_by_device_flow(flow)

if "refresh_token" in result:
    print("✅ Autenticación exitosa!\n")
    print("Guardá este valor como GitHub Secret con el nombre PBI_REFRESH_TOKEN:")
    print("-"*60)
    print(result["refresh_token"])
    print("-"*60)

    with open("token.json", "w") as f:
        json.dump({"refresh_token": result["refresh_token"]}, f)
    print("\nTambién guardado en token.json (no subas este archivo a GitHub)")
else:
    print(f"❌ Error: {result.get('error_description', result.get('error'))}")
