/* Conversión de voz — interfaz.
   El análisis de la voz lo hace Python (python/analisis_voz.py) dentro del
   navegador gracias a Pyodide; este archivo solo conecta la página con él. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var CLAVE_VOCES = 'conversion.voces';
  var CLAVE_SERVIDOR = 'conversion.servidor';
  var MAX_SEGUNDOS = 30;

  var py = null;            // funciones de Python
  var muestra = null;       // { canal: Float32Array, sr: number }
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

  // ---------- mensajes ----------
  function aviso(el, texto, tipo) {
    el.textContent = texto || '';
    el.className = 'mensaje' + (tipo ? ' ' + tipo : '');
  }

  // ---------- Python (Pyodide) ----------
  async function iniciarPython() {
    var estado = $('estado-python');
    try {
      var pyodide = await loadPyodide();
      await pyodide.loadPackage('numpy');
      var codigo = await (await fetch('python/analisis_voz.py')).text();
      pyodide.FS.writeFile('analisis_voz.py', codigo);
      pyodide.runPython([
        'import json, numpy as np, analisis_voz as av',
        'def analizar_js(arr, sr):',
        '    return json.dumps(av.analizar(np.asarray(arr.to_py(), dtype=np.float32), sr))',
        'def wav_js(arr, sr):',
        '    x = av.remuestrear(np.asarray(arr.to_py(), dtype=np.float64), sr, 22050)',
        '    return av.escribir_wav(x[: 22050 * av.MAX_SEGUNDOS], 22050)'
      ].join('\n'));
      py = {
        analizar: pyodide.globals.get('analizar_js'),
        wav: pyodide.globals.get('wav_js')
      };
      estado.className = 'pill pill--ok';
      estado.innerHTML = '<span class="punto"></span>Python listo en tu navegador (Pyodide ' + pyodide.version + ')';
      $('btn-analizar').disabled = !muestra;
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

  async function usarAudio(blob, nombre) {
    var msg = $('msg-crear');
    try {
      muestra = await decodificar(blob);
    } catch (e) {
      muestra = null;
      return aviso(msg, 'No se pudo leer el audio. Prueba con WAV o MP3.', 'error');
    }
    $('audio-muestra').src = URL.createObjectURL(blob);
    $('vista-previa').classList.remove('oculto');
    $('btn-analizar').disabled = !py;
    if (!$('nombre-voz').value && nombre) $('nombre-voz').value = nombre.replace(/\.[^.]+$/, '').slice(0, 60);
    var aviso2 = muestra.duracion > MAX_SEGUNDOS ? ' Se usarán los primeros ' + MAX_SEGUNDOS + ' s.' : '';
    aviso(msg, 'Audio de ' + muestra.duracion.toFixed(1) + ' s cargado.' + aviso2 + (py ? '' : ' Esperando a Python…'));
  }

  $('archivo').addEventListener('change', function (e) {
    var f = e.target.files[0];
    if (f) usarAudio(f, f.name);
  });
  var zona = $('zona-soltar');
  ['dragenter', 'dragover'].forEach(function (t) {
    zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.add('encima'); });
  });
  ['dragleave', 'drop'].forEach(function (t) {
    zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.remove('encima'); });
  });
  zona.addEventListener('drop', function (e) {
    var f = e.dataTransfer.files[0];
    if (f) usarAudio(f, f.name);
  });

  // Grabación con el micrófono
  var grabadora = null, reloj = null;
  $('btn-grabar').addEventListener('click', async function () {
    var btn = this;
    if (grabadora) { grabadora.stop(); return; }
    try {
      var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      return aviso($('msg-crear'), 'No hay permiso para usar el micrófono.', 'error');
    }
    var partes = [], inicio = Date.now();
    grabadora = new MediaRecorder(stream);
    grabadora.ondataavailable = function (e) { partes.push(e.data); };
    grabadora.onstop = function () {
      stream.getTracks().forEach(function (t) { t.stop(); });
      clearInterval(reloj);
      grabadora = null;
      btn.classList.remove('activo');
      btn.textContent = '● Grabar';
      $('tiempo-grabacion').textContent = 'Máx. ' + MAX_SEGUNDOS + ' s';
      usarAudio(new Blob(partes, { type: partes[0] && partes[0].type }), '');
    };
    grabadora.start();
    btn.classList.add('activo');
    btn.textContent = '■ Detener';
    reloj = setInterval(function () {
      var s = (Date.now() - inicio) / 1000;
      $('tiempo-grabacion').textContent = s.toFixed(0) + ' s';
      if (s >= MAX_SEGUNDOS && grabadora) grabadora.stop();
    }, 250);
  });

  // ---------- crear la voz ----------
  $('btn-analizar').addEventListener('click', async function () {
    var msg = $('msg-crear'), btn = this;
    if (!py || !muestra) return;
    btn.disabled = true;
    aviso(msg, 'Analizando tu voz con Python…');
    await new Promise(function (r) { setTimeout(r, 30); }); // deja pintar el mensaje
    try {
      var perfil = JSON.parse(py.analizar(muestra.canal, muestra.sr));
    } catch (e) {
      btn.disabled = false;
      var texto = String(e.message || e).trim().split('\n').pop().replace(/^ValueError:\s*/, '');
      return aviso(msg, texto, 'error');
    }
    var wavPy = py.wav(muestra.canal, muestra.sr);
    var wav = wavPy.toJs();
    wavPy.destroy();
    var voz = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      nombre: $('nombre-voz').value.trim() || 'Mi voz ' + (voces.length + 1),
      creada: new Date().toISOString(),
      perfil: perfil
    };
    await idb('readwrite', function (s) { return s.put(new Blob([wav], { type: 'audio/wav' }), voz.id); });
    voces.push(voz);
    guardar(CLAVE_VOCES, voces);
    seleccionar(voz.id);
    btn.disabled = false;
    aviso(msg, '¡Voz «' + voz.nombre + '» creada! Ahora escribe un texto en el paso 3.', 'ok');
    $('voces').scrollIntoView({ behavior: 'smooth' });
  });

  // ---------- lista y detalle de voces ----------
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
      chip.innerHTML = '<span></span><small>' + v.perfil.registro + ' · ' + Math.round(v.perfil.f0_media) + ' Hz</small>' +
        '<button class="quitar" type="button" aria-label="Borrar voz">×</button>';
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

  function seleccionar(id) {
    vozActiva = voces.filter(function (v) { return v.id === id; })[0] || null;
    pintarVoces();
    if (!vozActiva) return;
    var p = vozActiva.perfil;
    $('detalle-voz').classList.remove('oculto');
    var datos = [
      [Math.round(p.f0_media) + ' Hz', 'Tono medio (' + p.registro + ')'],
      [Math.round(p.f0_min) + '–' + Math.round(p.f0_max) + ' Hz', 'Rango de tono'],
      [p.expresividad.toFixed(1) + ' st', 'Expresividad'],
      [p.silabas_seg.toFixed(1) + ' síl/s', 'Velocidad'],
      [Math.round(p.brillo_hz) + ' Hz', 'Brillo del timbre'],
      [p.segundos_habla.toFixed(1) + ' s', 'Voz analizada']
    ];
    $('metricas').innerHTML = datos.map(function (d) {
      return '<div class="metrica"><b>' + d[0] + '</b><small>' + d[1] + '</small></div>';
    }).join('');
    graficar(p);
    $('pitch').value = p.tts.pitch;
    $('rate').value = p.tts.rate;
    actualizarSalidas();
    elegirVozSistema();
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
  window.addEventListener('resize', function () { if (vozActiva) graficar(vozActiva.perfil); });

  // ---------- texto a voz: navegador ----------
  var FEMENINAS = /(female|mujer|helena|laura|sabina|monica|mónica|paulina|elvira|dalia|lucia|lucía|conchita|penelope|lupe|ximena|marisol|paloma|camila|elena|isabela|francisca|catalina|google español)/i;
  var MASCULINAS = /(male|hombre|jorge|pablo|diego|carlos|juan|enrique|alvaro|álvaro|raul|raúl|miguel|gonzalo|andres|andrés|tomas|tomás|jose|josé)/i;

  function vocesSistema() {
    return ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
  }

  function llenarVocesSistema() {
    var sel = $('voz-sistema'), todas = vocesSistema();
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

  function actualizarSalidas() {
    $('out-pitch').textContent = Number($('pitch').value).toFixed(2);
    $('out-rate').textContent = Number($('rate').value).toFixed(2);
  }
  $('pitch').addEventListener('input', actualizarSalidas);
  $('rate').addEventListener('input', actualizarSalidas);

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

  // ---------- texto a voz: servidor de clonación ----------
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
      aviso(msg, 'Conectado. Modelo: ' + info.modelo + (info.cargado ? ' (cargado)' : ' (se cargará en la primera petición)'), 'ok');
    } catch (e) {
      aviso(msg, 'Sin conexión con el servidor: ' + e.message, 'error');
    }
  });

  async function registrarEnServidor(voz) {
    var url = urlServidor();
    if (voz.servidor && voz.servidor.url === url) return voz.servidor.id;
    var wav = await idb('readonly', function (s) { return s.get(voz.id); });
    if (!wav) throw new Error('No se encontró la muestra de esta voz en el navegador; vuelve a crearla.');
    var form = new FormData();
    form.append('nombre', voz.nombre);
    form.append('audio', wav, 'muestra.wav');
    var creada = await (await pedir('/api/voces', { method: 'POST', body: form })).json();
    voz.servidor = { url: url, id: creada.id };
    guardar(CLAVE_VOCES, voces);
    return creada.id;
  }

  async function hablarServidor(texto) {
    var msg = $('msg-hablar');
    aviso(msg, 'Subiendo tu voz al servidor…');
    var id = await registrarEnServidor(vozActiva);
    aviso(msg, 'Clonando tu voz con XTTS-v2… (la primera vez tarda en cargar el modelo)');
    var form = new FormData();
    form.append('texto', texto);
    form.append('idioma', $('idioma').value);
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
    aviso(msg, 'Listo: esta es tu voz clonada.', 'ok');
  }

  // ---------- controles ----------
  function motor() { return document.querySelector('input[name=motor]:checked').value; }
  document.querySelectorAll('input[name=motor]').forEach(function (r) {
    r.addEventListener('change', function () {
      var servidor = motor() === 'servidor';
      $('ajustes-servidor').classList.toggle('oculto', !servidor);
      $('ajustes-navegador').classList.toggle('oculto', servidor);
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
    try { await hablarServidor(texto); } catch (e) { aviso(msg, e.message, 'error'); }
    btn.disabled = false;
  });

  $('btn-detener').addEventListener('click', function () {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    $('audio-resultado').pause();
    aviso($('msg-hablar'), '');
  });

  // ---------- arranque ----------
  pintarVoces();
  if (voces.length) seleccionar(voces[voces.length - 1].id);
  iniciarPython();
})();
