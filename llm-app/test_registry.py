from app.modules.__init__ import get_module

dsa_config = get_module("dsa")
print(dsa_config.onboarding_prompt[:200])
print("-----")
print(f"Module ID: {dsa_config.module_id}, Name: {dsa_config.name}")
