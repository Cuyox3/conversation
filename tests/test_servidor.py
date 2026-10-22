import importlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from test_analisis_voz import SR, voz_sintetica  # noqa: E402


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERSION_VOCES", str(tmp_path))
    import server.app as app_mod

    app_mod = importlib.reload(app_mod)
    # Sustituye el modelo neuronal por uno falso para no descargar 2 GB
    monkeypatch.setattr(app_mod.clonador, "sintetizar", lambda texto, muestra, idioma: b"RIFF-falso")
    return TestClient(app_mod.app)


def test_flujo_completo(cliente):
    import analisis_voz as av

    wav = av.escribir_wav(voz_sintetica(130), SR)
    r = cliente.post("/api/voces", data={"nombre": "Arturo"}, files={"audio": ("voz.wav", wav, "audio/wav")})
    assert r.status_code == 200, r.text
    voz = r.json()
    assert voz["nombre"] == "Arturo" and voz["perfil"]["registro"] == "grave"

    assert [v["id"] for v in cliente.get("/api/voces").json()] == [voz["id"]]

    r = cliente.post(f"/api/voces/{voz['id']}/hablar", data={"texto": "Hola mundo"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"

    assert cliente.delete(f"/api/voces/{voz['id']}").json() == {"ok": True}
    assert cliente.get(f"/api/voces/{voz['id']}").status_code == 404


def test_rechaza_entradas_invalidas(cliente):
    r = cliente.post("/api/voces", data={"nombre": "x"}, files={"audio": ("a.wav", b"no es wav", "audio/wav")})
    assert r.status_code == 422
    assert cliente.get("/api/voces/../../etc").status_code == 404
    assert cliente.post("/api/voces/" + "0" * 32 + "/hablar", data={"texto": "hola"}).status_code == 404
