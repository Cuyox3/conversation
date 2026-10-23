import importlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import analisis_voz as av  # noqa: E402
import marca_agua as ma  # noqa: E402
from test_analisis_voz import SR, voz_sintetica  # noqa: E402


class MotorFalso:
    """Sustituye al modelo neuronal: devuelve 0.5 s de tono por fragmento."""

    sr = 16000
    idiomas = ["es", "en"]

    def __init__(self):
        self.llamadas = []

    def generar(self, texto, muestra, idioma, op):
        self.llamadas.append((texto, idioma, op))
        return voz_sintetica(150, segundos=0.5, sr=self.sr)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERSION_VOCES", str(tmp_path))
    import server.app as app_mod

    app_mod = importlib.reload(app_mod)
    motor = MotorFalso()
    monkeypatch.setattr(app_mod.clonador, "_motor", lambda nombre: motor)
    return TestClient(app_mod.app), motor


def crear(cliente, f0=130, consentimiento="true"):
    wav = av.escribir_wav(voz_sintetica(f0), SR)
    return cliente.post(
        "/api/voces",
        data={"nombre": "Arturo", "consentimiento": consentimiento},
        files={"audio": ("voz.wav", wav, "audio/wav")},
    )


def test_flujo_completo(entorno):
    cliente, motor = entorno
    r = crear(cliente)
    assert r.status_code == 200, r.text
    voz = r.json()
    assert voz["nombre"] == "Arturo" and voz["perfil"]["registro"] == "grave" and voz["consentimiento"]
    assert [v["id"] for v in cliente.get("/api/voces").json()] == [voz["id"]]

    texto = "Primera oración. " * 30  # más largo que un fragmento
    r = cliente.post(
        f"/api/voces/{voz['id']}/hablar",
        data={"texto": texto, "motor": "chatterbox", "emocion": "1.2", "velocidad": "9"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert len(motor.llamadas) > 1  # el texto se dividió en fragmentos
    op = motor.llamadas[0][2]
    assert op["emocion"] == 1.2 and op["velocidad"] == 2.0  # valores fuera de rango se acotan

    # El audio generado lleva marca de agua y el verificador la encuentra
    r = cliente.post("/api/verificar", files={"audio": ("g.wav", r.content, "audio/wav")})
    assert r.json()["marca"] is True

    assert cliente.delete(f"/api/voces/{voz['id']}").json() == {"ok": True}
    assert cliente.get(f"/api/voces/{voz['id']}").status_code == 404


def test_cambiador_de_voz(entorno):
    cliente, _ = entorno
    voz = crear(cliente, f0=220).json()
    fuente = av.escribir_wav(voz_sintetica(120, segundos=3), SR)
    r = cliente.post(f"/api/voces/{voz['id']}/convertir", files={"audio": ("f.wav", fuente, "audio/wav")})
    assert r.status_code == 200
    x, sr = av.leer_wav(r.content)
    assert av.analizar(x, sr)["f0_media"] == pytest.approx(220, rel=0.08)
    assert ma.detectar(x[:, 0])["marca"]


def test_verificar_audio_humano(entorno):
    cliente, _ = entorno
    wav = av.escribir_wav(voz_sintetica(150, segundos=3), SR)
    assert cliente.post("/api/verificar", files={"audio": ("h.wav", wav, "audio/wav")}).json()["marca"] is False


def test_rechaza_entradas_invalidas(entorno):
    cliente, _ = entorno
    assert crear(cliente, consentimiento="false").status_code == 403
    r = cliente.post(
        "/api/voces", data={"nombre": "x", "consentimiento": "true"},
        files={"audio": ("a.wav", b"no es wav", "audio/wav")},
    )
    assert r.status_code == 422
    assert cliente.get("/api/voces/../../etc").status_code == 404
    assert cliente.post("/api/voces/" + "0" * 32 + "/hablar", data={"texto": "hola"}).status_code == 404
    voz = crear(cliente).json()
    r = cliente.post(f"/api/voces/{voz['id']}/hablar", data={"texto": "hola", "motor": "otro"})
    assert r.status_code == 422
    r = cliente.post(f"/api/voces/{voz['id']}/hablar", data={"texto": "hola", "idioma": "xx"})
    assert r.status_code == 422


def test_dividir_texto():
    from server.clonador import dividir_texto

    texto = "Hola. " + "palabra " * 80 + "fin. ¿Qué tal? Bien."
    partes = dividir_texto(texto, maximo=100)
    assert all(len(p) <= 100 for p in partes)
    assert " ".join(partes).split() == texto.split()
    assert dividir_texto("Corto.") == ["Corto."]
    assert dividir_texto("a. " * 10, maximo=5) == ["a. a."] * 5
