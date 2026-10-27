const $ = (id) => document.getElementById(id);

let servoStepDeg = 15;
let statusFetchGen = 0;
const _servoStable = {
  base: { v: null, n: 0 },
  top: { v: null, n: 0 },
};

function _servoStableOk(key, val) {
  const s = _servoStable[key];
  if (s.v !== val) {
    s.v = val;
    s.n = 1;
    return false;
  }
  s.n += 1;
  return s.n >= 2;
}

function fillServoSelect(sel) {
  if (!sel || sel.options.length) return;
  for (let deg = 0; deg <= 180; deg += 15) {
    const o = document.createElement("option");
    o.value = String(deg);
    o.textContent = `${deg}°`;
    sel.appendChild(o);
  }
}

const SERVO_SELECT_STEP = 15;

function nearestServoDeg(deg) {
  if (!Number.isFinite(deg)) return null;
  const v = Math.round(deg / SERVO_SELECT_STEP) * SERVO_SELECT_STEP;
  return Math.max(0, Math.min(180, v));
}

function setServoSelectIfNeeded(sel, degFromServer) {
  if (!sel || !sel.options.length) return;
  const want = nearestServoDeg(degFromServer);
  if (want === null) return;
  const cur = Number(sel.value);
  if (cur === want) return;
  sel.value = String(want);
}

async function setServo(axis, payload) {
  const r = await fetch("/api/hardware/servo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ axis, ...payload }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) {
    const err = j.error || r.statusText || "Request failed";
    console.warn("Servo:", err);
  }
  return r.ok && j.ok;
}

function renderGpsMap(lat, lon) {
  const map = $("gpsMap");
  const links = $("gpsLinks");
  if (!map || !links) return;
  if (lat == null || lon == null) {
    map.src = "https://maps.google.com/maps?q=34.0522,-118.2437&z=10&hl=en&output=embed";
    links.innerHTML =
      '<a href="https://maps.google.com/?hl=en" target="_blank" rel="noopener noreferrer">Open in Google Maps</a> · No location yet (searching for satellites)';
    return;
  }
  const la = Number(lat);
  const lo = Number(lon);
  const laR = Math.round(la * 1000) / 1000;
  const loR = Math.round(lo * 1000) / 1000;
  const g = `https://maps.google.com/maps?q=${laR},${loR}&z=14&hl=en&output=embed`;
  map.src = g;
  const gg = `https://maps.google.com/?q=${laR},${loR}&hl=en`;
  const osm = `https://www.openstreetmap.org/?mlat=${laR}&mlon=${loR}#map=14/${laR}/${loR}`;
  links.innerHTML = `<a href="${gg}" target="_blank" rel="noopener noreferrer">Open in Google Maps</a> · <a href="${osm}" target="_blank" rel="noopener noreferrer">Open in OpenStreetMap</a>`;
}

let ivHb = null;
let ivTick = null;
let hbFailStreak = 0;
let lastTickOkAt = 0;

function disableHeartbeatUseStatusOnly() {
  if (window.__noHeartbeat) return;
  window.__noHeartbeat = true;
  if (ivHb != null) {
    clearInterval(ivHb);
    ivHb = null;
  }
  if (ivTick != null) clearInterval(ivTick);
  ivTick = setInterval(tick, 1000);
  hbFailStreak = 0;
  tick();
}

function applyAlarmsLogAndBorder(d) {
  $("pillBlue").classList.toggle("on", !!d.blue_led);
  $("pillRed").classList.toggle("on", !!d.red_led);
  const camCard = document.querySelector(".cam-card");
  if (camCard) {
    camCard.classList.toggle("emergency", !!(d.red_led || d.emergency_active));
  }
  const log = $("log");
  if (log) {
    log.innerHTML = "";
    (d.events || []).slice(0, 40).forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      log.appendChild(li);
    });
  }
}

function applyEnvGpsMotionFromPayload(d, updateMap) {
  $("temp").textContent = d.temperature_c != null ? d.temperature_c : "—";
  $("hum").textContent = d.humidity_pct != null ? d.humidity_pct : "—";
  $("boardTemp").textContent = d.board_temp_c != null ? d.board_temp_c : "—";

  let dhtHint = "";
  if (d.dht_ok) {
    dhtHint = "DHT temperature and humidity readings are normal.";
  } else if (d.temperature_source === "dht_partial") {
    dhtHint =
      "The DHT sensor returned partial data. Check BCM18, the pull-up resistor, wiring stability, and that DHT_TYPE matches the DHT11/22 model.";
  } else {
    dhtHint =
      "No DHT reading. Check BCM18 wiring, 3.3 V power, the pull-up resistor, and DHT_TYPE; install Adafruit_DHT with apt or pip if needed. Board temperature is the SoC temperature.";
  }
  if (d.dht_error && String(d.dht_error).trim()) {
    dhtHint += " — " + d.dht_error;
  }
  $("dhtHint").textContent = dhtHint;

  const m = Math.min(100, (d.motion_score || 0) * 8);
  $("motionBar").style.width = `${m}%`;
  $("motionVal").textContent = String(d.motion_score ?? 0);

  $("irVal").textContent = d.ir_motion ? "Signal / HIGH" : "No signal / LOW";

  if (d.gps_lat != null && d.gps_lon != null) {
    $("gps").textContent = `${d.gps_lat}, ${d.gps_lon} · ${d.gps_status || "Position acquired"}`;
  } else {
    const sats = Number.isFinite(d.gps_sats) ? d.gps_sats : 0;
    $("gps").textContent = d.gps_status || `Searching for satellites (${sats} visible)`;
  }
  if (updateMap) renderGpsMap(d.gps_lat, d.gps_lon);
}

async function heartbeat() {
  if (window.__noHeartbeat) return;
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch("/api/heartbeat", {
      cache: "no-store",
      credentials: "include",
      signal: ctrl.signal,
    });
    clearTimeout(to);
    if (r.status === 401) {
      $("liveDot").classList.remove("on");
      $("liveText").textContent =
        "Unauthorized: this dashboard requires a username and password. Reopen the page and sign in.";
      return;
    }
    if (r.status === 404) {
      disableHeartbeatUseStatusOnly();
      return;
    }
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();

    hbFailStreak = 0;
    $("liveDot").classList.add("on");
    const lt = $("liveText");
    if (lt && !lt.dataset.fullOk) {
      lt.textContent = "Online · Temperature, humidity, and GPS update at a slower rate; logs and alerts are active";
    }
    applyAlarmsLogAndBorder(d);
    applyEnvGpsMotionFromPayload(d, false);
  } catch (e) {
    clearTimeout(to);
    hbFailStreak += 1;
    const noStatusForMs = Date.now() - lastTickOkAt;
    if (hbFailStreak >= 25 && noStatusForMs > 30000) {
      $("liveDot").classList.remove("on");
      const lt = $("liveText");
      if (lt) delete lt.dataset.fullOk;
      $("liveText").textContent = "Disconnected · Check the elder-car service and port 5000";
    }
  }
}

async function tick() {
  const myGen = ++statusFetchGen;
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch("/api/status", {
      cache: "no-store",
      credentials: "include",
      signal: ctrl.signal,
    });
    clearTimeout(to);
    if (r.status === 401) {
      $("liveDot").classList.remove("on");
      $("liveText").textContent =
        "Unauthorized: this dashboard requires a username and password. Reopen the page and sign in.";
      return;
    }
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    if (myGen !== statusFetchGen) return;

    lastTickOkAt = Date.now();
    hbFailStreak = 0;
    $("liveDot").classList.add("on");
    const lt = $("liveText");
    if (lt) {
      lt.dataset.fullOk = "1";
      lt.textContent = "Connected · Environmental, GPS, and camera data synchronized";
    }

    applyAlarmsLogAndBorder(d);
    applyEnvGpsMotionFromPayload(d, true);

    if (Number.isFinite(d.servo_step_deg)) {
      servoStepDeg = Math.max(1, Math.min(45, d.servo_step_deg));
    }

    $("camTag").textContent = d.camera_ok ? "Online" : "Offline";
    $("camHint").textContent = d.camera_ok
      ? ""
      : d.camera_error
        ? `Reason: ${d.camera_error}`
        : "The camera is disconnected or disabled";

    const servoCard = $("servoCard");
    const baseSel = $("servoBaseSel");
    const topSel = $("servoTopSel");
    if (servoCard && baseSel && topSel) {
      if (d.servo_enabled) {
        fillServoSelect(baseSel);
        fillServoSelect(topSel);
        servoCard.classList.remove("servo-disabled");
        const tag = $("servoTag");
        if (tag) tag.textContent = "Enabled";
        const sb = Number(d.servo_base_deg);
        const st = Number(d.servo_top_deg);
        if (Number.isFinite(sb) && _servoStableOk("base", sb)) {
          setServoSelectIfNeeded(baseSel, sb);
        }
        if (Number.isFinite(st) && _servoStableOk("top", st)) {
          setServoSelectIfNeeded(topSel, st);
        }
      } else {
        servoCard.classList.add("servo-disabled");
        const tag = $("servoTag");
        if (tag) tag.textContent = "Disabled";
      }
    }
  } catch (e) {
    clearTimeout(to);
    const slow = e && e.name === "AbortError";
    const lt = $("liveText");
    if (lt) delete lt.dataset.fullOk;
    if (lt) {
      lt.textContent = slow
        ? "Temperature, humidity, and GPS request timed out; if the event log is updating, the service is still running"
        : "Temperature, humidity, and GPS are temporarily unavailable; the event log may still update through the fast endpoint";
    }
    hbFailStreak += 4;
    if (hbFailStreak >= 25 && Date.now() - lastTickOkAt > 30000) {
      $("liveDot").classList.remove("on");
      $("liveText").textContent = "Disconnected · Check the elder-car service and port 5000";
    }
  }
}

function wireServoUi() {
  const baseSel = $("servoBaseSel");
  const topSel = $("servoTopSel");
  const step = () => servoStepDeg;

  baseSel?.addEventListener("change", () => {
    const v = Number(baseSel.value);
    if (Number.isFinite(v)) setServo("base", { angle: v });
  });
  topSel?.addEventListener("change", () => {
    const v = Number(topSel.value);
    if (Number.isFinite(v)) setServo("top", { angle: v });
  });

  $("servoBaseLeft")?.addEventListener("click", () =>
    setServo("base", { delta: -step() }),
  );
  $("servoBaseRight")?.addEventListener("click", () =>
    setServo("base", { delta: step() }),
  );
  $("servoTopDown")?.addEventListener("click", () =>
    setServo("top", { delta: -step() }),
  );
  $("servoTopUp")?.addEventListener("click", () =>
    setServo("top", { delta: step() }),
  );
}

lastTickOkAt = Date.now();
heartbeat();
tick();
ivHb = setInterval(heartbeat, 400);
ivTick = setInterval(tick, 2000);
wireServoUi();
