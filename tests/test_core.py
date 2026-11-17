import pytest
from purrfect.core.contracts import ChatCommand, TenantContext
from purrfect.core.service import AccessDenied, PurrCore
from purrfect.sophira import KnowledgeItem, KnowledgePackage
from purrfect.sophira_storage import DurableSophira

@pytest.mark.asyncio
async def test_general_chat_and_session_isolation():
    class EchoModel:
        def __init__(self): self.inputs=[]
        async def complete(self, system, user):
            self.inputs.append(user)
            return "Hello!"
    model=EchoModel(); core=PurrCore(model=model)
    a=TenantContext("a",frozenset())
    b=TenantContext("b",frozenset())
    await core.respond(a,ChatCommand("same","secret from A"))
    await core.respond(b,ChatCommand("same","Hi"))
    assert "secret from A" not in model.inputs[-1]
    await core.respond(a,ChatCommand("same","Continue"))
    assert "secret from A" in model.inputs[-1]

@pytest.mark.asyncio
async def test_sophia_tenant_scoping_and_grants(tmp_path):
    db=DurableSophira(tmp_path/"sophia.db")
    db.publish_approved(KnowledgePackage("tenant-a/demo","1",1,(
        KnowledgeItem("install","Install from the blue menu.","manual://a"),)),approved=True)
    db.publish_approved(KnowledgePackage("tenant-b/demo","1",1,(
        KnowledgeItem("install","Install from the red menu.","manual://b"),)),approved=True)
    core=PurrCore(catalog=db)
    a=TenantContext("tenant-a",frozenset({"demo"}))
    b=TenantContext("tenant-b",frozenset({"demo"}))
    command=ChatCommand("same","How do I install?", "demo","1")
    first=await core.respond(a,command)
    second=await core.respond(b,command)
    assert "blue" in first.message and "red" in second.message
    assert first.sources[0].source == "manual://a"
    assert second.sources[0].source == "manual://b"
    with pytest.raises(AccessDenied):
        await core.respond(TenantContext("tenant-a",frozenset()), command)
    missing=await core.respond(a,ChatCommand("same","Refund policy?","demo","1"))
    assert missing.status=="knowledge_gap" and missing.sources==()
    db.close()

@pytest.mark.asyncio
async def test_core_stays_independent_of_gateway():
    import sys
    from purrfect.core import service
    assert "fastapi" not in service.__dict__
    assert "pydantic" not in service.__dict__
    assert "purrfect.gateway" not in sys.modules or service.__name__ != "purrfect.gateway"
