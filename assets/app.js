/* Conversión de voz — interfaz.
   El procesamiento de voz lo hace Python (carpeta python/) dentro del
   navegador gracias a Pyodide; este archivo solo conecta la página con él. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var CLAVE_VOCES = 'conversion.voces';
  var CLAVE_SERVIDOR = 'conversion.servidor';
  var MAX_SEGUNDOS = 30;
  var MODULOS = ['analisis_voz.py', 'cambiador_voz.py', 'marca_agua.py'];

  var py = null;            // funciones de Python
  var muestra = null;       // audio para crear la voz: { canal, sr, duracion }
  var fuenteCambio = null;  // audio para el cambiador
  var perfilFuente = null;  // perfil del audio a convertir
  var voces = cargar(CLAVE_VOCES, []);
  var vozActiva = null;

  // ---------- almacenamiento ----------
  function cargar(clave, porDefecto) {
    try { var v = localStorage.getItem(clave); return v ? JSON.parse(v) : porDefecto; } catch (e) { return porDefecto; }
  }
  function guardar(clave, valor) {
    try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* modo privado */ }
  }

  // Las muestras WAV se guardan en IndexedDB para poder clonarlas después en el servidor
  var db = new Promise(function (ok) {
    try {
      var req = indexedDB.open('conversion', 1);
      req.onupgradeneeded = function () { req.result.createObjectStore('muestras'); };
      req.onsuccess = function () { ok(req.result); };
      req.onerror = function () { ok(null); };
    } catch (e) { ok(null); }
  });
  function idb(modo, accion) {
    return db.then(function (d) {
      if (!d) return null;
      return new Promise(function (ok) {
        var tx = d.transaction('muestras', modo);
        var req = accion(tx.objectStore('muestras'));
        tx.oncomplete = function () { ok(req.result); };
        tx.onerror = function () { ok(null); };
      });
    });
  }

  // ---------- utilidades ----------
  function aviso(el, texto, tipo) {
    el.textContent = texto || '';
    el.className = 'mensaje' + (tipo ? ' ' + tipo : '');
  }
  function errorPython(e) {
    return String(e.message || e).trim().split('\n').pop().replace(/^\w*Error:\s*/, '');
  }
  function pausa() { return new Promise(function (r) { setTimeout(r, 30); }); } // deja pintar mensajes
  function blobWav(pyBytes) {
    var datos = pyBytes.toJs();
    pyBytes.destroy();
    return new Blob([datos], { type: 'audio/wav' });
  }
  function enlazarSlider(id, formato) {
    var actualizar = function () { $('out-' + id).textContent = formato(Number($(id).value)); };
    $(id).addEventListener('input', actualizar);
    actualizar();
    return actualizar;
  }

  // ---------- Python (Pyodide) ----------
  async function iniciarPython() {
    var estado = $('estado-python');
    try {
      var pyodide = await loadPyodide();
      await pyodide.loadPackage('numpy');
      await Promise.all(MODULOS.map(async function (m) {
        pyodide.FS.writeFile(m, await (await fetch('python/' + m)).text());
      }));
      pyodide.runPython([
        'import json, numpy as np, analisis_voz as av, cambiador_voz as cv, marca_agua as ma',
        'def _np(arr):',
        '    return np.asarray(arr.to_py(), dtype=np.float64)',
        'def analizar_js(arr, sr):',
        '    return json.dumps(av.analizar(_np(arr), sr))',
        'def wav_js(arr, sr):',
        '    x = av.remuestrear(_np(arr), sr, 22050)',
        '    return av.escribir_wav(x[: 22050 * av.MAX_SEGUNDOS], 22050)',
        'def disenar_js(f0, silabas, expresividad):',
        '    return json.dumps(av.disenar(f0, silabas, expresividad))',
        'def factores_js(origen, destino):',
        '    return json.dumps(cv.factores_hacia(json.loads(origen), json.loads(destino)))',
        'def convertir_js(arr, sr, tono, formantes):',
        '    x = _np(arr)[: int(sr * av.MAX_SEGUNDOS)]',
        '    y, sr_y = cv.cambiar(x, sr, tono, formantes)',
        '    return av.escribir_wav(ma.insertar(y), sr_y)',
        'def verificar_js(datos):',
        '    x, sr = av.leer_wav(bytes(datos.to_py()))',
        '    return json.dumps(ma.detectar(x.mean(axis=1)))'
      ].join('\n'));
      py = {};
      ['analizar', 'wav', 'disenar', 'factores', 'convertir', 'verificar'].forEach(function (f) {
        py[f] = pyodide.globals.get(f + '_js');
      });
      estado.className = 'pill pill--ok';
      estado.innerHTML = '<span class="punto"></span>Python listo en tu navegador (Pyodide ' + pyodide.version + ')';
      actualizarBotonCrear();
      $('btn-disenar').disabled = false;
    } catch (e) {
      estado.className = 'pill pill--error';
      estado.innerHTML = '<span class="punto"></span>No se pudo cargar Python: ' + e.message;
    }
  }

  // ---------- entrada de audio ----------
  async function decodificar(blob) {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    try {
      var buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
      var n = buffer.length, canal = new Float32Array(n);
      for (var c = 0; c < buffer.numberOfChannels; c++) {
        var d = buffer.getChannelData(c);
        for (var i = 0; i < n; i++) canal[i] += d[i] / buffer.numberOfChannels;
      }
      return { canal: canal, sr: buffer.sampleRate, duracion: buffer.duration };
    } finally { ctx.close(); }
  }

  // Botón de grabación reutilizable (crear voz y cambiador)
  function grabadora(btn, etiqueta, alTerminar) {
    var rec = null, reloj = null;
    btn.addEventListener('click', async function () {
      if (rec) { rec.stop(); return; }
      try {
        var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        etiqueta.textContent = 'Sin permiso de micrófono';
        return;
      }
      var partes = [], inicio = Date.now();
      rec = new MediaRecorder(stream);
      rec.ondataavailable = function (e) { partes.push(e.data); };
      rec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        clearInterval(reloj);
        rec = null;
        btn.classList.remove('activo');
        btn.textContent = '● Grabar';
        etiqueta.textContent = 'Máx. ' + MAX_SEGUNDOS + ' s';
        alTerminar(new Blob(partes, { type: partes[0] && partes[0].type }), '');
      };
      rec.start();
      btn.classList.add('activo');
      btn.textContent = '■ Detener';
      reloj = setInterval(function () {
        var s = (Date.now() - inicio) / 1000;
        etiqueta.textContent = s.toFixed(0) + ' s';
        if (s >= MAX_SEGUNDOS && rec) rec.stop();
      }, 250);
    });
  }

  function zonaSoltar(input, alElegir) {
    var zona = input.closest('.soltar');
    input.addEventListener('change', function (e) { var f = e.target.files[0]; if (f) alElegir(f, f.name); });
    ['dragenter', 'dragover'].forEach(function (t) {
      zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.add('encima'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.remove('encima'); });
    });
    zona.addEventListener('drop', function (e) { var f = e.dataTransfer.files[0]; if (f) alElegir(f, f.name); });
  }

  // ---------- 1. crear la voz ----------
  document.querySelectorAll('.pestana').forEach(function (p) {
    p.addEventListener('click', function () {
      document.querySelectorAll('.pestana').forEach(function (o) {
        var activa = o === p;
        o.classList.toggle('activa', activa);
        o.setAttribute('aria-selected', activa);
        $(o.dataset.panel).classList.toggle('oculto', !activa);
      });
      aviso($('msg-crear'), '');
    });
  });

  function actualizarBotonCrear() {
    $('btn-analizar').disabled = !(py && muestra && $('consentimiento').checked);
  }
  $('consentimiento').addEventListener('change', actualizarBotonCrear);

  async function usarMuestra(blob, nombre) {
    var msg = $('msg-crear');
    try {
      muestra = await decodificar(blob);
    } catch (e) {
      muestra = null;
      actualizarBotonCrear();
      return aviso(msg, 'No se pudo leer el audio. Prueba con WAV o MP3.', 'error');
    }
    $('audio-muestra').src = URL.createObjectURL(blob);
    $('vista-previa').classList.remove('oculto');
    actualizarBotonCrear();
    if (!$('nombre-voz').value && nombre) $('nombre-voz').value = nombre.replace(/\.[^.]+$/, '').slice(0, 60);
    var extra = muestra.duracion > MAX_SEGUNDOS ? ' Se usarán los primeros ' + MAX_SEGUNDOS + ' s.' : '';
    var falta = !$('consentimiento').checked ? ' Marca la casilla de consentimiento para continuar.' : '';
    aviso(msg, 'Audio de ' + muestra.duracion.toFixed(1) + ' s cargado.' + extra + falta + (py ? '' : ' Esperando a Python…'));
  }
  zonaSoltar($('archivo'), usarMuestra);
  grabadora($('btn-grabar'), $('tiempo-grabacion'), usarMuestra);

  async function agregarVoz(perfil, wav) {
    var voz = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      nombre: $('nombre-voz').value.trim() || 'Mi voz ' + (voces.length + 1),
      creada: new Date().toISOString(),
      perfil: perfil
    };
    if (wav) {
      voz.consentimiento = voz.creada;
      await idb('readwrite', function (s) { return s.put(wav, voz.id); });
    }
    voces.push(voz);
    guardar(CLAVE_VOCES, voces);
    seleccionar(voz.id);
    $('nombre-voz').value = '';
    return voz;
  }

  $('btn-analizar').addEventListener('click', async function () {
    var msg = $('msg-crear'), btn = this;
    if (!py || !muestra) return;
    btn.disabled = true;
    aviso(msg, 'Analizando tu voz con Python…');
    await pausa();
    try {
      var perfil = JSON.parse(py.analizar(muestra.canal, muestra.sr));
    } catch (e) {
      actualizarBotonCrear();
      return aviso(msg, errorPython(e), 'error');
    }
    var voz = await agregarVoz(perfil, blobWav(py.wav(muestra.canal, muestra.sr)));
    actualizarBotonCrear();
    var nota = perfil.calidad.nivel === 'baja' ? ' La calidad de la muestra es baja: revisa los consejos.' : '';
    aviso(msg, '¡Voz «' + voz.nombre + '» creada!' + nota, 'ok');
    $('voces').scrollIntoView({ behavior: 'smooth' });
  });

  enlazarSlider('d-tono', function (v) { return v + ' Hz'; });
  enlazarSlider('d-vel', function (v) { return v.toFixed(1) + ' síl/s'; });
  enlazarSlider('d-exp', function (v) { return v.toFixed(1) + ' st'; });
  $('btn-disenar').addEventListener('click', async function () {
    var perfil = JSON.parse(py.disenar(Number($('d-tono').value), Number($('d-vel').value), Number($('d-exp').value)));
    var voz = await agregarVoz(perfil, null);
    aviso($('msg-crear'), '¡Voz diseñada «' + voz.nombre + '» creada!', 'ok');
  });

  // ---------- 2. lista y detalle de voces ----------
  function pintarVoces() {
    var lista = $('lista-voces');
    if (!voces.length) {
      lista.innerHTML = '<p class="vacio">Aún no has creado ninguna voz.</p>';
      $('detalle-voz').classList.add('oculto');
      return;
    }
    lista.innerHTML = '';
    voces.forEach(function (v) {
      var chip = document.createElement('div');
      chip.className = 'chip' + (vozActiva && vozActiva.id === v.id ? ' activa' : '');
      chip.setAttribute('role', 'button');
      chip.tabIndex = 0;
      chip.innerHTML = '<span></span><small>' + (v.perfil.disenada ? 'diseñada · ' : '') + v.perfil.registro + ' · ' +
        Math.round(v.perfil.f0_media) + ' Hz</small><button class="quitar" type="button" aria-label="Borrar voz">×</button>';
      chip.firstChild.textContent = v.nombre;
      chip.addEventListener('click', function () { seleccionar(v.id); });
      chip.addEventListener('keydown', function (e) { if (e.key === 'Enter') seleccionar(v.id); });
      chip.querySelector('.quitar').addEventListener('click', function (e) {
        e.stopPropagation();
        if (!confirm('¿Borrar la voz «' + v.nombre + '»?')) return;
        voces = voces.filter(function (x) { return x.id !== v.id; });
        guardar(CLAVE_VOCES, voces);
        idb('readwrite', function (s) { return s.delete(v.id); });
        seleccionar(voces.length ? voces[voces.length - 1].id : null);
      });
      lista.appendChild(chip);
    });
  }

  function pintarCalidad(c) {
    var caja = $('calidad');
    if (!c) { caja.classList.add('oculto'); return; }
    caja.className = 'calidad calidad--' + c.nivel;
    caja.innerHTML = '<b>' + c.puntos + '</b><span>Calidad de la muestra: <strong>' + c.nivel + '</strong> · ruido de fondo a ' +
      c.snr_db + ' dB de la voz</span>' + (c.consejos.length ? '<ul>' + c.consejos.map(function (t) { return '<li>' + t + '</li>'; }).join('') + '</ul>' : '<span>Lista para clonar.</span>');
  }

  function seleccionar(id) {
    vozActiva = voces.filter(function (v) { return v.id === id; })[0] || null;
    pintarVoces();
    if (!vozActiva) return;
    var p = vozActiva.perfil;
    $('detalle-voz').classList.remove('oculto');
    pintarCalidad(p.calidad);
    var datos = [
      [Math.round(p.f0_media) + ' Hz', 'Tono medio (' + p.registro + ')'],
      [Math.round(p.f0_min) + '–' + Math.round(p.f0_max) + ' Hz', 'Rango de tono'],
      [p.expresividad.toFixed(1) + ' st', 'Expresividad'],
      [p.silabas_seg.toFixed(1) + ' síl/s', 'Velocidad']
    ];
    if (p.brillo_hz) datos.push([Math.round(p.brillo_hz) + ' Hz', 'Brillo del timbre']);
    if (p.segundos_habla) datos.push([p.segundos_habla.toFixed(1) + ' s', 'Voz analizada']);
    $('metricas').innerHTML = datos.map(function (d) {
      return '<div class="metrica"><b>' + d[0] + '</b><small>' + d[1] + '</small></div>';
    }).join('');
    $('grafica-tono').classList.toggle('oculto', !p.contorno.length);
    if (p.contorno.length) graficar(p);
    $('pitch').value = p.tts.pitch;
    $('rate').value = p.tts.rate;
    actualizarPitch(); actualizarRate();
    elegirVozSistema();
    if (perfilFuente) proponerFactores();
  }

  function graficar(p) {
    var c = $('grafica-tono'), ctx = c.getContext('2d');
    var dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = 160;
    c.width = w * dpr; c.height = h * dpr;
    ctx.scale(dpr, dpr);
    var estilo = getComputedStyle(document.documentElement);
    var suave = estilo.getPropertyValue('--suave').trim(), acento = estilo.getPropertyValue('--acento').trim();
    var vals = p.contorno, max = Math.max(p.f0_max * 1.25, 200), pad = 28;
    ctx.clearRect(0, 0, w, h);
    ctx.font = '11px Inter, sans-serif';
    ctx.fillStyle = suave;
    ctx.strokeStyle = suave;
    ctx.globalAlpha = 0.25;
    [100, 200, 300, 400].forEach(function (f) {
      if (f > max) return;
      var y = h - 16 - (f / max) * (h - 26);
      ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - 6, y); ctx.stroke();
      ctx.globalAlpha = 1; ctx.fillText(f, 2, y + 4); ctx.globalAlpha = 0.25;
    });
    ctx.globalAlpha = 1;
    ctx.fillText('Tono (Hz) a lo largo de ' + (vals.length * p.contorno_ms / 1000).toFixed(1) + ' s', pad, h - 3);
    ctx.strokeStyle = acento;
    ctx.lineWidth = 2;
    ctx.beginPath();
    var trazando = false;
    vals.forEach(function (v, i) {
      var x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad - 6);
      if (!v) { trazando = false; return; }
      var y = h - 16 - (v / max) * (h - 26);
      if (trazando) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      trazando = true;
    });
    ctx.stroke();
  }
  window.addEventListener('resize', function () { if (vozActiva && vozActiva.perfil.contorno.length) graficar(vozActiva.perfil); });

  // ---------- 3. texto a voz: navegador ----------
  var FEMENINAS = /(female|mujer|helena|laura|sabina|monica|mónica|paulina|elvira|dalia|lucia|lucía|conchita|penelope|lupe|ximena|marisol|paloma|camila|elena|isabela|francisca|catalina|google español)/i;
  var MASCULINAS = /(male|hombre|jorge|pablo|diego|carlos|juan|enrique|alvaro|álvaro|raul|raúl|miguel|gonzalo|andres|andrés|tomas|tomás|jose|josé)/i;

  function llenarVocesSistema() {
    var sel = $('voz-sistema'), todas = ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
    var es = todas.filter(function (v) { return /^es/i.test(v.lang); });
    var lista = es.length ? es : todas;
    sel.innerHTML = lista.map(function (v, i) {
      return '<option value="' + i + '">' + v.name + ' (' + v.lang + ')</option>';
    }).join('') || '<option>Tu navegador no tiene voces</option>';
    sel._lista = lista;
    elegirVozSistema();
  }

  function elegirVozSistema() {
    var sel = $('voz-sistema'), lista = sel._lista || [];
    if (!vozActiva || !lista.length) return;
    var patron = vozActiva.perfil.tts.genero === 'masculina' ? MASCULINAS : FEMENINAS;
    for (var i = 0; i < lista.length; i++) {
      if (patron.test(lista[i].name) && !(patron === MASCULINAS && /female/i.test(lista[i].name))) {
        sel.value = String(i);
        return;
      }
    }
  }

  if ('speechSynthesis' in window) {
    llenarVocesSistema();
    speechSynthesis.onvoiceschanged = llenarVocesSistema;
  }

  var actualizarPitch = enlazarSlider('pitch', function (v) { return v.toFixed(2); });
  var actualizarRate = enlazarSlider('rate', function (v) { return v.toFixed(2); });
  ['velocidad', 'emocion', 'fidelidad', 'temperatura'].forEach(function (id) {
    enlazarSlider(id, function (v) { return v.toFixed(2); });
  });
  var contar = function () { $('contador').textContent = $('texto').value.length + ' / 5000'; };
  $('texto').addEventListener('input', contar);
  contar();

  function hablarNavegador(texto) {
    if (!('speechSynthesis' in window)) throw new Error('Tu navegador no soporta texto a voz.');
    speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(texto);
    var sel = $('voz-sistema');
    if (sel._lista && sel._lista[sel.value]) {
      u.voice = sel._lista[sel.value];
      u.lang = u.voice.lang;
    } else {
      u.lang = 'es-MX';
    }
    u.pitch = Number($('pitch').value);
    u.rate = Number($('rate').value);
    u.onend = function () { aviso($('msg-hablar'), 'Listo.', 'ok'); };
    speechSynthesis.speak(u);
    aviso($('msg-hablar'), 'Reproduciendo con «' + (u.voice ? u.voice.name : u.lang) + '»…');
  }

  // ---------- 3. texto a voz: servidor de clonación ----------
  $('url-servidor').value = cargar(CLAVE_SERVIDOR, '');
  function urlServidor() {
    var url = $('url-servidor').value.trim().replace(/\/+$/, '');
    guardar(CLAVE_SERVIDOR, url);
    if (!url) throw new Error('Escribe la URL de tu servidor de clonación (ver README).');
    return url;
  }

  async function pedir(ruta, opciones) {
    var r = await fetch(urlServidor() + ruta, opciones);
    if (!r.ok) {
      var detalle = '';
      try { detalle = (await r.json()).detail; } catch (e) { /* sin JSON */ }
      throw new Error(detalle || ('Error ' + r.status));
    }
    return r;
  }

  $('btn-probar').addEventListener('click', async function () {
    var msg = $('msg-hablar');
    try {
      var info = await (await pedir('/api/salud')).json();
      var motores = Object.keys(info.motores).map(function (m) {
        return m + (info.motores[m].cargado ? ' (cargado)' : '');
      }).join(', ');
      aviso(msg, 'Conectado. Motores: ' + motores + '. Cada modelo se carga en su primera petición.', 'ok');
    } catch (e) {
      aviso(msg, 'Sin conexión con el servidor: ' + e.message, 'error');
    }
  });

  async function registrarEnServidor(voz) {
    var url = urlServidor();
    if (voz.servidor && voz.servidor.url === url) return voz.servidor.id;
    var wav = await idb('readonly', function (s) { return s.get(voz.id); });
    if (!wav) throw new Error('Esta voz no tiene grabación (es diseñada o se borró del navegador). Crea una voz a partir de un audio.');
    var form = new FormData();
    form.append('nombre', voz.nombre);
    form.append('audio', wav, 'muestra.wav');
    form.append('consentimiento', voz.consentimiento ? 'true' : 'false');
    var creada = await (await pedir('/api/voces', { method: 'POST', body: form })).json();
    voz.servidor = { url: url, id: creada.id };
    guardar(CLAVE_VOCES, voces);
    return creada.id;
  }

  async function hablarServidor(texto, nombreMotor) {
    var msg = $('msg-hablar');
    aviso(msg, 'Subiendo tu voz al servidor…');
    var id = await registrarEnServidor(vozActiva);
    aviso(msg, 'Clonando tu voz con ' + nombreMotor + '… (la primera vez tarda en cargar el modelo)');
    var form = new FormData();
    form.append('texto', texto);
    form.append('idioma', $('idioma').value);
    form.append('motor', nombreMotor);
    ['velocidad', 'emocion', 'fidelidad', 'temperatura'].forEach(function (k) { form.append(k, $(k).value); });
    var r;
    try {
      r = await pedir('/api/voces/' + id + '/hablar', { method: 'POST', body: form });
    } catch (e) {
      if (/no encontrada/i.test(e.message)) { vozActiva.servidor = null; guardar(CLAVE_VOCES, voces); }
      throw e;
    }
    var url = URL.createObjectURL(await r.blob());
    $('audio-resultado').src = url;
    $('descargar').href = url;
    $('resultado').classList.remove('oculto');
    $('audio-resultado').play();
    aviso(msg, 'Listo: esta es tu voz clonada (incluye marca de agua).', 'ok');
  }

  function motor() { return document.querySelector('input[name=motor]:checked').value; }
  document.querySelectorAll('input[name=motor]').forEach(function (r) {
    r.addEventListener('change', function () {
      var m = motor(), servidor = m !== 'navegador';
      $('ajustes-servidor').classList.toggle('oculto', !servidor);
      $('ajustes-navegador').classList.toggle('oculto', servidor);
      document.querySelectorAll('.solo-xtts').forEach(function (el) { el.classList.toggle('oculto', m !== 'xtts'); });
      document.querySelectorAll('.solo-chatterbox').forEach(function (el) { el.classList.toggle('oculto', m !== 'chatterbox'); });
      aviso($('msg-hablar'), '');
    });
  });

  $('btn-hablar').addEventListener('click', async function () {
    var btn = this, msg = $('msg-hablar'), texto = $('texto').value.trim();
    if (!texto) return aviso(msg, 'Escribe un texto.', 'error');
    if (motor() === 'navegador') {
      try { hablarNavegador(texto); } catch (e) { aviso(msg, e.message, 'error'); }
      return;
    }
    if (!vozActiva) return aviso(msg, 'Primero crea o elige una voz (pasos 1 y 2).', 'error');
    btn.disabled = true;
    try { await hablarServidor(texto, motor()); } catch (e) { aviso(msg, e.message, 'error'); }
    btn.disabled = false;
  });

  $('btn-detener').addEventListener('click', function () {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    $('audio-resultado').pause();
    aviso($('msg-hablar'), '');
  });

  // ---------- 4. cambiador de voz ----------
  enlazarSlider('c-tono', function (v) { return '×' + v.toFixed(2); });
  enlazarSlider('c-form', function (v) { return '×' + v.toFixed(2); });

  function proponerFactores() {
    if (!py || !perfilFuente || !vozActiva) return;
    var f = JSON.parse(py.factores(JSON.stringify(perfilFuente), JSON.stringify(vozActiva.perfil)));
    $('c-tono').value = f[0];
    $('c-form').value = f[1];
    ['c-tono', 'c-form'].forEach(function (id) { $(id).dispatchEvent(new Event('input')); });
  }

  async function usarFuente(blob) {
    var msg = $('msg-cambio');
    if (!py) return aviso(msg, 'Espera a que cargue Python.', 'error');
    try {
      fuenteCambio = await decodificar(blob);
    } catch (e) {
      return aviso(msg, 'No se pudo leer el audio.', 'error');
    }
    $('audio-fuente').src = URL.createObjectURL(blob);
    $('ajustes-cambio').classList.remove('oculto');
    $('resultado-cambio').classList.add('oculto');
    try {
      perfilFuente = JSON.parse(py.analizar(fuenteCambio.canal, fuenteCambio.sr));
    } catch (e) {
      perfilFuente = null;
      return aviso(msg, errorPython(e), 'error');
    }
    proponerFactores();
    aviso(msg, 'Tu grabación tiene un tono medio de ' + Math.round(perfilFuente.f0_media) + ' Hz.' +
      (vozActiva ? ' Ajusté tono y timbre para llevarla a «' + vozActiva.nombre + '».' : ' Elige una voz destino en el paso 2.'));
  }
  zonaSoltar($('archivo-cambio'), usarFuente);
  grabadora($('btn-grabar-cambio'), $('tiempo-cambio'), usarFuente);

  $('btn-convertir').addEventListener('click', async function () {
    var msg = $('msg-cambio'), btn = this;
    if (!fuenteCambio) return;
    btn.disabled = true;
    aviso(msg, 'Convirtiendo con Python… (unos segundos)');
    await pausa();
    try {
      var blob = blobWav(py.convertir(fuenteCambio.canal, fuenteCambio.sr, Number($('c-tono').value), Number($('c-form').value)));
      var url = URL.createObjectURL(blob);
      $('audio-cambio').src = url;
      $('descargar-cambio').href = url;
      $('resultado-cambio').classList.remove('oculto');
      $('audio-cambio').play();
      aviso(msg, 'Listo. El resultado incluye marca de agua.', 'ok');
    } catch (e) {
      aviso(msg, errorPython(e), 'error');
    }
    btn.disabled = false;
  });

  // ---------- 5. verificar marca de agua ----------
  zonaSoltar($('archivo-verificar'), async function (archivo) {
    var msg = $('msg-verificar');
    if (!py) return aviso(msg, 'Espera a que cargue Python.', 'error');
    try {
      var r = JSON.parse(py.verificar(new Uint8Array(await archivo.arrayBuffer())));
    } catch (e) {
      return aviso(msg, 'Solo se pueden verificar archivos WAV PCM.', 'error');
    }
    msg.className = 'mensaje';
    msg.innerHTML = '<span class="veredicto veredicto--' + (r.marca ? 'si' : 'no') + '">' +
      (r.marca ? 'Generado por Conversión' : 'Sin marca de Conversión') + '</span> puntuación ' + r.puntuacion +
      ' (umbral 6) en ' + r.bloques + ' bloques';
  });

  // ---------- arranque ----------
  pintarVoces();
  if (voces.length) seleccionar(voces[voces.length - 1].id);
  iniciarPython();
})();
