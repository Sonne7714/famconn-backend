from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["devtools"])


@router.get("/dev/login-test", response_class=HTMLResponse)
async def login_test_page():
    html = """
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>FamConn Dev Login Test</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --card: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #dbe3ef;
      --blue: #0b57d0;
      --blue-dark: #0a47aa;
      --black: #111111;
      --ok: #0f9d58;
      --err: #d93025;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .wrap {
      max-width: 1080px;
      margin: 0 auto;
      padding: 24px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.08);
      margin-bottom: 18px;
    }
    h1, h2 {
      margin: 0 0 12px 0;
    }
    p {
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    .row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .field {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    label {
      font-weight: 700;
      font-size: 13px;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid #cfd8e3;
      border-radius: 12px;
      padding: 12px 14px;
      font: inherit;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 150px;
      resize: vertical;
      font-family: Consolas, monospace;
      font-size: 13px;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      font-weight: 800;
      cursor: pointer;
      background: var(--blue);
      color: white;
    }
    button.secondary { background: var(--black); }
    button.ghost {
      background: #eef4ff;
      color: #17375d;
      border: 1px solid #dbe7ff;
    }
    button:hover { filter: brightness(0.97); }
    .status {
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      font-weight: 700;
      display: none;
    }
    .status.ok { display: block; background: #eaf7ef; color: var(--ok); }
    .status.err { display: block; background: #fdecea; color: var(--err); }
    pre {
      margin: 0;
      background: #0f172a;
      color: #e5edf7;
      border-radius: 14px;
      padding: 14px;
      overflow: auto;
      font-family: Consolas, monospace;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .mono {
      font-family: Consolas, monospace;
      font-size: 13px;
    }
    .token-box {
      margin-top: 14px;
      padding: 12px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 14px;
    }
    .small {
      font-size: 12px;
      color: var(--muted);
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>FamConn – Login-Testseite</h1>
      <p>Interne Testoberfläche für Login, Token und API-Aufrufe direkt gegen dein lokales Backend.</p>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Login</h2>

        <div class="field">
          <label for="email">E-Mail</label>
          <input id="email" type="email" placeholder="deine@email.de" />
        </div>

        <div class="field">
          <label for="password">Kennwort</label>
          <input id="password" type="password" placeholder="Kennwort" />
        </div>

        <div class="row" style="margin-top:16px;">
          <button id="loginBtn">Einloggen</button>
          <button id="logoutBtn" class="secondary" type="button">Token löschen</button>
          <button id="togglePwdBtn" class="ghost" type="button">Kennwort anzeigen</button>
        </div>

        <div id="loginStatus" class="status"></div>

        <div class="token-box">
          <div style="font-weight:800; margin-bottom:8px;">Access Token</div>
          <div id="tokenInfo" class="small">Kein Token gespeichert.</div>
          <div style="margin-top:10px;">
            <button id="copyTokenBtn" class="ghost" type="button">Token kopieren</button>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Schnelltests</h2>
        <div class="row">
          <button class="ghost" type="button" data-path="/health" data-method="GET">/health</button>
          <button class="ghost" type="button" data-path="/api/v1/auth/me" data-method="GET">/api/v1/auth/me</button>
          <button class="ghost" type="button" data-path="/api/v1/family/me" data-method="GET">/api/v1/family/me</button>
        </div>

        <div class="field">
          <label for="familyId">Family ID für Detailtests</label>
          <input id="familyId" type="text" placeholder="z. B. 67f..." />
        </div>

        <div class="row" style="margin-top:12px;">
          <button id="familyMembersBtn" class="ghost" type="button">/api/v1/family/{id}/members</button>
          <button id="locationMembersBtn" class="ghost" type="button">/api/v1/location/family/{id}/members</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Freier API-Test</h2>
      <div class="grid">
        <div>
          <div class="field">
            <label for="method">Methode</label>
            <select id="method">
              <option>GET</option>
              <option>POST</option>
              <option>PUT</option>
              <option>PATCH</option>
              <option>DELETE</option>
            </select>
          </div>

          <div class="field">
            <label for="path">Pfad</label>
            <input id="path" type="text" value="/health" />
          </div>

          <div class="field">
            <label for="body">JSON-Body</label>
            <textarea id="body">{
  "email": "",
  "password": ""
}</textarea>
          </div>

          <div class="row">
            <button id="sendBtn" type="button">Absenden</button>
            <button id="formatBtn" class="secondary" type="button">JSON formatieren</button>
          </div>
        </div>

        <div>
          <div style="font-weight:800; margin-bottom:10px;">Antwort</div>
          <pre id="output">Noch keine Anfrage gesendet.</pre>
        </div>
      </div>
    </div>
  </div>

  <script>
    const TOKEN_KEY = "famconn_dev_access_token";

    const emailEl = document.getElementById("email");
    const passwordEl = document.getElementById("password");
    const familyIdEl = document.getElementById("familyId");
    const tokenInfoEl = document.getElementById("tokenInfo");
    const loginStatusEl = document.getElementById("loginStatus");
    const outputEl = document.getElementById("output");
    const pathEl = document.getElementById("path");
    const methodEl = document.getElementById("method");
    const bodyEl = document.getElementById("body");

    function getToken() {
      return window.localStorage.getItem(TOKEN_KEY) || "";
    }

    function setToken(token) {
      if (token) {
        window.localStorage.setItem(TOKEN_KEY, token);
      } else {
        window.localStorage.removeItem(TOKEN_KEY);
      }
      renderTokenInfo();
    }

    function renderTokenInfo() {
      const token = getToken();
      if (!token) {
        tokenInfoEl.textContent = "Kein Token gespeichert.";
        return;
      }
      const shortToken = token.length > 120 ? token.slice(0, 120) + " …" : token;
      tokenInfoEl.innerHTML = '<div class="mono">' + escapeHtml(shortToken) + '</div>';
    }

    function setStatus(type, text) {
      loginStatusEl.className = "status " + type;
      loginStatusEl.textContent = text;
    }

    function clearStatus() {
      loginStatusEl.className = "status";
      loginStatusEl.textContent = "";
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function pretty(value) {
      try {
        return JSON.stringify(value, null, 2);
      } catch {
        return String(value);
      }
    }

    async function apiCall(path, method = "GET", body = null, useAuth = true) {
      const headers = { "Content-Type": "application/json" };
      const token = getToken();
      if (useAuth && token) {
        headers["Authorization"] = "Bearer " + token;
      }

      const response = await fetch(path, {
        method,
        headers,
        body: body == null ? undefined : JSON.stringify(body),
      });

      const text = await response.text();
      let parsed;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = text;
      }

      return {
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        data: parsed,
      };
    }

    async function runAndRender(path, method, body, useAuth = true) {
      outputEl.textContent = "Lade ...";
      try {
        const result = await apiCall(path, method, body, useAuth);
        outputEl.textContent =
          method + " " + path + "\\n" +
          "Status: " + result.status + " " + result.statusText + "\\n\\n" +
          pretty(result.data);
      } catch (error) {
        outputEl.textContent = "Fehler\\n\\n" + String(error);
      }
    }

    document.getElementById("loginBtn").addEventListener("click", async () => {
      clearStatus();
      const email = emailEl.value.trim();
      const password = passwordEl.value;

      if (!email || !password) {
        setStatus("err", "Bitte E-Mail und Kennwort eingeben.");
        return;
      }

      try {
        const result = await apiCall("/api/v1/auth/login", "POST", { email, password }, false);
        if (!result.ok || !result.data || !result.data.access_token) {
          setStatus("err", "Login fehlgeschlagen.");
          outputEl.textContent = pretty(result.data);
          return;
        }

        setToken(result.data.access_token);
        setStatus("ok", "Login erfolgreich.");
        outputEl.textContent = pretty(result.data);
      } catch (error) {
        setStatus("err", "Login fehlgeschlagen: " + String(error));
      }
    });

    document.getElementById("logoutBtn").addEventListener("click", () => {
      setToken("");
      setStatus("ok", "Token wurde gelöscht.");
    });

    document.getElementById("togglePwdBtn").addEventListener("click", () => {
      passwordEl.type = passwordEl.type === "password" ? "text" : "password";
    });

    document.getElementById("copyTokenBtn").addEventListener("click", async () => {
      const token = getToken();
      if (!token) {
        setStatus("err", "Kein Token vorhanden.");
        return;
      }
      try {
        await navigator.clipboard.writeText(token);
        setStatus("ok", "Token kopiert.");
      } catch {
        setStatus("err", "Token konnte nicht kopiert werden.");
      }
    });

    document.querySelectorAll("[data-path]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const path = btn.getAttribute("data-path");
        const method = btn.getAttribute("data-method") || "GET";
        await runAndRender(path, method, null, path !== "/health");
      });
    });

    document.getElementById("familyMembersBtn").addEventListener("click", async () => {
      const id = familyIdEl.value.trim();
      if (!id) {
        setStatus("err", "Bitte zuerst eine Family ID eintragen.");
        return;
      }
      await runAndRender(`/api/v1/family/${encodeURIComponent(id)}/members`, "GET", null, true);
    });

    document.getElementById("locationMembersBtn").addEventListener("click", async () => {
      const id = familyIdEl.value.trim();
      if (!id) {
        setStatus("err", "Bitte zuerst eine Family ID eintragen.");
        return;
      }
      await runAndRender(`/api/v1/location/family/${encodeURIComponent(id)}/members`, "GET", null, true);
    });

    document.getElementById("sendBtn").addEventListener("click", async () => {
      const method = methodEl.value;
      const path = pathEl.value.trim();
      if (!path) {
        outputEl.textContent = "Bitte einen Pfad eingeben.";
        return;
      }

      let body = null;
      if (!["GET", "DELETE"].includes(method)) {
        const raw = bodyEl.value.trim();
        if (raw) {
          try {
            body = JSON.parse(raw);
          } catch (error) {
            outputEl.textContent = "Ungültiges JSON im Body\\n\\n" + String(error);
            return;
          }
        }
      }

      await runAndRender(path, method, body, path !== "/health");
    });

    document.getElementById("formatBtn").addEventListener("click", () => {
      try {
        const parsed = JSON.parse(bodyEl.value);
        bodyEl.value = JSON.stringify(parsed, null, 2);
      } catch (error) {
        outputEl.textContent = "JSON konnte nicht formatiert werden\\n\\n" + String(error);
      }
    });

    renderTokenInfo();
  </script>
</body>
</html>
"""
    return HTMLResponse(html)
