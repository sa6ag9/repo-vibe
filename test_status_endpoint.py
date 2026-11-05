import io
import json
from unittest.mock import patch
import app

def invoke(path):
    handler=object.__new__(app.H)
    handler.path=path
    handler.wfile=io.BytesIO()
    result={}
    handler.send_response=lambda code:result.update(code=code)
    handler.send_header=lambda *args:None
    handler.end_headers=lambda:None
    handler.do_GET()
    result["body"]=handler.wfile.getvalue()
    return result

def test_status_public_only():
    with patch.object(app,"api",return_value={"private":False}),patch.object(app.repo_vibe,"fetch_stats",return_value={"stars":5,"secret":"hidden"}):
        response=invoke("/status/example/repo")
    assert response["code"]==200
    payload=json.loads(response["body"])
    assert payload["stars"]==5 and "secret" not in payload

def test_status_private_never_fetches_stats():
    with patch.object(app,"api",return_value={"private":True}),patch.object(app.repo_vibe,"fetch_stats") as fetch:
        response=invoke("/status/example/private")
    assert response["code"]==404
    fetch.assert_not_called()
