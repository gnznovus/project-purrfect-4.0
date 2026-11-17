import pytest
from purrfect.provider import Purr
from purrfect.sophira import KnowledgeItem, KnowledgePackage
from purrfect.sophira_storage import DurableSophira

def test_chat_and_validation():
    p = Purr()
    assert p.respond({"session_id": "a", "message": "Hi!"})["status"] == "conversation"
    for bad in ({"message":"Hi"}, {"session_id":"a","message":""}, {"session_id":"a","message":"Hi","inventory":{}}, {"session_id":"a","message":"Hi","product_id":"x"}):
        with pytest.raises(ValueError):
            p.respond(bad)

def test_grounding(tmp_path):
    db = DurableSophira(tmp_path / "approved.db")
    db.publish_approved(KnowledgePackage("product","1",1,(KnowledgeItem("install","Install with setup wizard.","manual://install"),)),approved=True)
    p = Purr(catalog=db)
    request = {"session_id":"a","product_id":"product","product_version":"1"}
    ok = p.respond(request | {"message":"How do I install?"})
    assert ok["status"] == "grounded" and ok["sources"][0]["id"] == "install"
    assert p.respond(request | {"message":"Refund policy?"})["status"] == "knowledge_gap"
    assert p.respond(request | {"message":"install","product_version":"2"})["status"] == "knowledge_gap"
    db.close()

def test_model_history():
    class Model:
        def __init__(self): self.calls=[]
        async def complete(self, system, user):
            self.calls.append(user)
            return "Hello there!"
    m=Model(); p=Purr(model=m)
    p.respond({"session_id":"a","message":"Hello"})
    p.respond({"session_id":"a","message":"Again"})
    assert "User: Hello" in m.calls[-1]
