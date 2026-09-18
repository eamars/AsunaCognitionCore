import uuid
import pytest
from asuna.config import load
from asuna.state import Store

@pytest.fixture
def store():
    db=Store(load(),'asuna_v2_test_M1_'+uuid.uuid4().hex[:12])
    db.migrate();db.seed()
    yield db
    db.client.close()
    # Tests retain their isolated databases for audit; no broad cleanup.
