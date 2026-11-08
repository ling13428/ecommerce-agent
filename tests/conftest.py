import os

os.environ["SESSION_PERSISTENCE"] = "false"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["AUTH_SECRET"] = "test-auth-secret"
os.environ["AGENT_CHECKPOINT_BACKEND"] = "memory"
os.environ["CACHE_BACKEND"] = "memory"
os.environ["ORDERS_BACKEND"] = "sqlite"
os.environ["PRODUCT_PROVIDER"] = "mock"
os.environ["ORDER_PROVIDER"] = "mock"
os.environ["AUDIT_ENABLED"] = "false"
