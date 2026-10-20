"use strict";
// Giao diện Rewards Bot. Mọi dữ liệu đến từ Python (window.pywebview.api) và sự kiện window.onEvents.

const S = { settings: {}, profiles: [], pstate: {}, history: {}, running: new Set(),
            logs: [], unreadErr: 0, selected: null, page: "dashboard" };
const api = () => window.pywebview.api;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// chỉ hiển thị ảnh https từ bing.com (dữ liệu lấy từ trang web bên ngoài nên không tin tuyệt đối)
const safeImg = (u) => (/^https:\/\/([a-z0-9-]+\.)*bing\.com\//i.test(u || "") ? u : "");
const fmt = (n) => (n === null || n === undefined || n === "" ? "—" : Number(n).toLocaleString("en-US"));
const SERIES = [["pc", "Search PC", "#2a78d6"], ["mobile", "Search Mobile", "#eb6834"], ["offers", "Offers", "#1baf7a"]];
const RUN_STATES = ["Đang chạy", "Đang chờ", "Đang làm mới", "Đang đăng nhập"];
const GROUP_ORDER = ["Tìm kiếm", "Daily Set", "Keep earning", "Hoạt động", "Task thêm"];
const CHECK = '<svg viewBox="0 0 12 12"><path d="M2.5 6.5 5 9l4.5-6"/></svg>';

// ===================================================================== khởi động
window.addEventListener("pywebviewready", async () => {
  const b = await api().bootstrap();
  Object.assign(S, b, { running: new Set(b.running) });
  S.selected = S.profiles[0]?.name ?? null;
  bindStatic();
  renderAll();
});

window.onEvents = (batch) => {
  let dirty = false;
  for (const e of batch) {
    if (e.type === "log") {
      S.logs.push(e);
      if (/^\s*(lỗi|cảnh báo)/i.test(e.msg)) S.unreadErr++;
      if (S.page === "log") appendLog(e);
    } else if (e.type === "status") {
      const st = (S.pstate[e.name] ||= {});
      Object.assign(st, e.data);
      if (e.history) S.history[e.name] = e.history;
      if (RUN_STATES.includes(e.data.state)) S.running.add(e.name);
      dirty = true;
    } else if (e.type === "done") {
      S.running.delete(e.name); dirty = true;
    }
  }
  if (S.logs.length > 4000) S.logs = S.logs.slice(-3000);
  if (dirty) { renderSide(); if (S.page === "dashboard") renderDashboard(); if (S.page === "profiles") renderProfiles(); }
  renderLogBadge();
};

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
}

// ===================================================================== điều hướng + nút cố định
function bindStatic() {
  $$("nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));
  $("#btn-refresh").onclick = () => S.selected && start([S.selected], "refresh");
  $("#btn-run-one").onclick = () => S.selected && start([S.selected], "run");
  $("#btn-run-all").onclick = () => start(null, "run");
  $("#btn-stop-all").onclick = async () => { await api().stop(null); toast("Đã gửi lệnh dừng"); };
  $("#btn-add").onclick = () => openProfileDialog(null);
  $("#btn-clear-log").onclick = () => { S.logs = []; S.unreadErr = 0; renderLog(); renderLogBadge(); };
  $("#log-filter").onchange = renderLog;
  $("#btn-save-settings").onclick = saveSettingsForm;
  $("#max-parallel").onchange = (e) => saveSettings({ max_parallel: Math.max(1, +e.target.value || 1) });
  bindProfileDialog();
  document.addEventListener("mouseleave", hideTip);
}

function go(page) {
  S.page = page;
  $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach((p) => (p.hidden = p.id !== "page-" + page));
  if (page === "log") S.unreadErr = 0;
  renderAll();
}

async function start(names, action) {
  const r = await api().start(names, action);
  if (r.ok === false) { toast(r.error); return; }
  r.running.forEach((n) => S.running.add(n));
  renderSide(); renderDashboard(); renderProfiles();
  toast({ run: "Bắt đầu chạy", refresh: "Đang làm mới điểm", login: "Đã mở cửa sổ đăng nhập" }[action]);
}

function renderAll() {
  renderSide();
  if (S.page === "dashboard") renderDashboard();
  if (S.page === "profiles") renderProfiles();
  if (S.page === "log") renderLog();
  if (S.page === "settings") renderSettings();
  renderLogBadge();
}

function renderSide() {
  $("#brand-sub").textContent = `${S.profiles.length} tài khoản`;
  const on = S.running.size > 0;
  $("#run-state").classList.toggle("on", on);
  $("#run-state span:last-child").textContent = on ? `Đang chạy ${S.running.size} tài khoản` : "Đang nghỉ";
}

function renderLogBadge() {
  const b = $("#log-badge");
  b.hidden = !S.unreadErr || S.page === "log";
  b.textContent = S.unreadErr;
}

const initials = (n) => n.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const st = (name) => S.pstate[name] || {};

function statePill(name) {
  const s = st(name).state || "Sẵn sàng";
  const cls = RUN_STATES.includes(s) ? "run" : s === "Hoàn thành" ? "done" : ["Lỗi", "Chưa đăng nhập"].includes(s) ? "err" : "idle";
  return `<span class="pill ${cls}">${esc(s)}</span>`;
}

// ===================================================================== tổng quan
function renderDashboard() {
  const chips = $("#profile-chips");
  if (!S.profiles.length) {
    chips.innerHTML = `<button class="btn primary" id="btn-first-profile">Thêm tài khoản đầu tiên</button>`;
    $("#btn-first-profile").addEventListener("click", () => { go("profiles"); openProfileDialog(null); });
  } else {
    chips.innerHTML = S.profiles.map((p) => `
      <button class="chip ${p.name === S.selected ? "active" : ""}" data-name="${esc(p.name)}">
        <span class="avatar" data-run="${S.running.has(p.name) ? 1 : 0}">${esc(initials(p.name))}</span>
        <span>${esc(p.name)}</span><span class="pts">${fmt(st(p.name).points)}</span>
      </button>`).join("");
    $$(".chip", chips).forEach((c) => (c.onclick = () => { S.selected = c.dataset.name; renderDashboard(); }));
  }
  const name = S.selected;
  const s = st(name);
  const stats = s.stats || {};
  $("#hero-avatar").textContent = name ? initials(name) : "";
  $("#hero-name").textContent = name || "Chưa có tài khoản";
  $("#hero-state").textContent = name ? `${s.state || "Sẵn sàng"}${s.progress ? " · " + s.progress : ""}` : "";
  $("#hero-points").textContent = fmt(s.points);
  $("#hero-today").textContent = s.today != null ? "+" + fmt(s.today) : "—";
  $("#hero-month").textContent = fmt(stats.month);
  $("#hero-life").textContent = fmt(stats.lifetime);
  $("#btn-run-one").disabled = !name || S.running.has(name);
  $("#btn-refresh").disabled = !name || S.running.has(name);
  $("#tasks-updated").textContent = s.updated ? "Cập nhật " + s.updated : "";
  renderStamps(s);
  renderMeters(s);
  renderTasks(s);
  const hist = S.history[name] || {};
  const days = Object.keys(hist).sort();
  const lab = (d) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
  $("#legend-daily").innerHTML = SERIES.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("");
  stackChart($("#chart-daily"), days.slice(-14).map((d) => ({ label: lab(d), v: hist[d] })));
  lineChart($("#chart-balance"), days.slice(-30).filter((d) => hist[d].available != null).map((d) => ({ label: lab(d), v: hist[d].available })));
}

function renderStamps(s) {
  // mỗi task có điểm của hôm nay là 1 con dấu: search PC/Mobile, Daily Set, Keep earning
  const tasks = (s.tasks || []).filter((t) => ["Tìm kiếm", "Daily Set", "Keep earning"].includes(t.group));
  const box = $("#stamps");
  if (!tasks.length) {
    box.innerHTML = `<p class="empty-note">Chưa có dữ liệu. Bấm <b>Làm mới</b> để đọc task hôm nay từ Rewards.</p>`;
    $("#stamp-count").textContent = "";
    return;
  }
  const done = tasks.filter((t) => t.done).length;
  $("#stamp-count").textContent = `${done}/${tasks.length} dấu`;
  box.innerHTML = tasks.map((t) => `
    <div class="stamp ${t.done ? "done" : ""}" data-tip="${esc(t.title)}|${t.done ? "Đã xong" : "Chưa làm"}|+${t.max} điểm">
      <div class="stamp-wrap"><div class="disc">${t.img ? `<img src="${esc(safeImg(t.img))}" alt="" loading="lazy">` : `<span class="fallback">${esc(initials(t.title))}</span>`}</div>
      <span class="check">${CHECK}</span></div>
      <span class="pts">+${t.max}</span>
    </div>`).join("");
  $$(".stamp", box).forEach((el) => {
    el.onmousemove = (e) => { const [a, b, c] = el.dataset.tip.split("|"); showTip(e, `<b>${esc(a)}</b><div class="row">${esc(b)}<span>${esc(c)}</span></div>`); };
    el.onmouseleave = hideTip;
  });
}

function renderMeters(s) {
  const stats = s.stats || {};
  const icons = s.icons || {};
  const rows = [["pc", "Search PC", icons["Tìm kiếm"]], ["mobile", "Search Mobile", icons["Mobile"]]];
  const findImg = (title) => (s.tasks || []).find((t) => t.title === title)?.img;
  $("#meters").innerHTML = rows.map(([k, label, ic]) => {
    const p = stats[k], m = stats[k + "_max"], color = SERIES.find((x) => x[0] === k)[2];
    const img = findImg(label) || ic;
    return `<div class="meter">${img ? `<img src="${esc(safeImg(img))}" alt="">` : "<span></span>"}
      <span class="label">${label}</span><span class="val">${m ? `${p}/${m} điểm` : "chưa có dữ liệu"}</span>
      <div class="track"><div class="fill" style="width:${m ? Math.min(100, (p / m) * 100) : 0}%;background:${color}"></div></div></div>`;
  }).join("");
}

function renderTasks(s) {
  const tasks = s.tasks || [];
  const box = $("#task-groups");
  if (!tasks.length) { box.innerHTML = `<p class="empty-note">Chưa có dữ liệu task cho tài khoản này.</p>`; return; }
  const groups = {};
  tasks.forEach((t) => (groups[t.group] ||= []).push(t));
  const icons = s.icons || {};
  box.innerHTML = Object.keys(groups)
    .sort((a, b) => (GROUP_ORDER.indexOf(a) + 99) % 99 - (GROUP_ORDER.indexOf(b) + 99) % 99)
    .map((g) => {
      const items = groups[g], d = items.filter((t) => t.done).length;
      const gi = icons[g] || items[0]?.img;
      return `<div class="tgroup"><h3>${gi ? `<img src="${esc(safeImg(gi))}" alt="">` : ""}${esc(g)}<span class="count">${d}/${items.length} xong</span></h3>
        ${items.map((t) => {
          const pct = t.max ? Math.min(100, (t.progress / t.max) * 100) : 0;
          return `<div class="task ${t.done ? "done" : ""}">
            ${t.img ? `<img class="thumb" src="${esc(safeImg(t.img))}" alt="" loading="lazy">` : `<span class="thumb"></span>`}
            <div><div class="t" title="${esc(t.title)}">${esc(t.title)}</div>
              <div class="sub">${t.progress}/${t.max} ${esc(t.unit || "điểm")}</div><div class="bar"><div style="width:${pct}%"></div></div></div>
            <span class="pill ${t.done ? "done" : "todo"}">${t.done ? "Xong" : "Chưa xong"}</span></div>`;
        }).join("")}</div>`;
    }).join("");
}

// ===================================================================== biểu đồ SVG
function niceMax(v, ticks = 4) {
  if (v <= 0) return 10 * ticks;
  for (let mag = 1; ; mag *= 10)
    for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8]) { const s = m * mag; if (Number.isInteger(s) && s * ticks >= v) return s * ticks; }
}
function showTip(e, html) {
  const t = $("#tooltip"); t.innerHTML = html; t.hidden = false;
  const r = t.getBoundingClientRect();
  t.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 8) + "px";
  t.style.top = Math.max(e.clientY - r.height - 10, 8) + "px";
}
function hideTip() { $("#tooltip").hidden = true; }
const tipRows = (rows) => rows.map(([c, l, v]) => `<div class="row"><i style="background:${c}"></i>${l}<span>${v}</span></div>`).join("");

function stackChart(el, data) {
  if (!data.length) { el.innerHTML = `<div class="empty">Chưa có lịch sử. Mỗi lần chạy hoặc làm mới sẽ ghi lại điểm của ngày đó.</div>`; return; }
  const W = el.clientWidth || 600, H = el.clientHeight || 230, L = 38, R = 6, T = 14, B = 24;
  const totals = data.map((d) => SERIES.reduce((a, [k]) => a + (d.v[k] || 0), 0));
  const ymax = niceMax(Math.max(...totals)), slot = (W - L - R) / data.length, bw = Math.min(26, slot * 0.58);
  const y = (v) => H - B - ((H - B - T) * v) / ymax;
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = (ymax * i) / 4;
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="${i ? "#eef0f5" : "#c9cfdc"}"/>`;
    svg += `<text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  const step = Math.max(1, Math.ceil((data.length * 46) / (W - L - R)));
  data.forEach((d, i) => {
    const cx = L + slot * (i + 0.5);
    let base = H - B;
    SERIES.forEach(([k, , c], si) => {
      const v = d.v[k] || 0; if (v <= 0) return;
      const h = ((H - B - T) * v) / ymax;
      const top = base - h, isTop = SERIES.slice(si + 1).every(([k2]) => !(d.v[k2] > 0));
      svg += isTop
        ? `<path d="M${cx - bw / 2},${base} V${top + 4} q0,-4 4,-4 H${cx + bw / 2 - 4} q4,0 4,4 V${base} Z" fill="${c}"/>`
        : `<rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${h}" fill="${c}"/>`;
      base = top - 2;
    });
    if ((data.length - 1 - i) % step === 0) svg += `<text class="axis" x="${cx}" y="${H - 6}" text-anchor="middle">${d.label}</text>`;
    svg += `<rect class="hit" data-i="${i}" x="${L + slot * i}" y="${T}" width="${slot}" height="${H - B - T}" fill="transparent"/>`;
  });
  const last = data.length - 1;
  svg += `<text x="${L + slot * (last + 0.5)}" y="${y(totals[last]) - 6}" text-anchor="middle" font-weight="600" font-size="12" fill="#19202f">${totals[last]}</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${svg}</svg>`;
  $$(".hit", el).forEach((r) => {
    r.onmousemove = (e) => { const d = data[+r.dataset.i]; showTip(e, `<b>${d.label} · ${totals[+r.dataset.i]} điểm</b>` + tipRows(SERIES.map(([k, l, c]) => [c, l, d.v[k] || 0]))); };
    r.onmouseleave = hideTip;
  });
}

function lineChart(el, data) {
  if (!data.length) { el.innerHTML = `<div class="empty">Chưa có lịch sử điểm.</div>`; return; }
  const W = el.clientWidth || 400, H = el.clientHeight || 230, L = 52, R = 14, T = 22, B = 24;
  const vals = data.map((d) => d.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.15, 10); lo = Math.max(0, lo - pad); hi += pad;
  const x = (i) => (data.length > 1 ? L + ((W - L - R) * i) / (data.length - 1) : (L + W - R) / 2);
  const y = (v) => H - B - ((H - B - T) * (v - lo)) / (hi - lo);
  let svg = "";
  for (let i = 0; i <= 3; i++) {
    const v = lo + ((hi - lo) * i) / 3;
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="${i ? "#eef0f5" : "#c9cfdc"}"/>`;
    svg += `<text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(Math.round(v))}</text>`;
  }
  const pts = data.map((d, i) => [x(i), y(d.v)]);
  if (pts.length > 1) {
    svg += `<path d="M${pts.map((p) => p.join(",")).join(" L")} L${pts.at(-1)[0]},${H - B} L${pts[0][0]},${H - B} Z" fill="rgba(42,120,214,.08)"/>`;
    svg += `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#2a78d6" stroke-width="2" stroke-linejoin="round"/>`;
  }
  const [lx, ly] = pts.at(-1);
  svg += `<circle cx="${lx}" cy="${ly}" r="4.5" fill="#2a78d6" stroke="#fff" stroke-width="2"/>`;
  svg += `<text x="${lx - 8}" y="${ly - 10}" text-anchor="end" font-weight="600" font-size="12" fill="#19202f">${fmt(data.at(-1).v)}</text>`;
  const step = Math.max(1, Math.ceil((data.length * 46) / (W - L - R)));
  data.forEach((d, i) => { if ((data.length - 1 - i) % step === 0) svg += `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="${i === data.length - 1 ? "end" : "middle"}">${d.label}</text>`; });
  svg += `<line id="xh" y1="${T}" y2="${H - B}" stroke="#c9cfdc" stroke-dasharray="3 3" visibility="hidden"/><circle id="xd" r="5" fill="#2a78d6" stroke="#fff" stroke-width="2" visibility="hidden"/>`;
  svg += `<rect id="hitl" x="${L}" y="${T}" width="${W - L - R}" height="${H - B - T}" fill="transparent"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${svg}</svg>`;
  const s = $("svg", el), hit = $("#hitl", el), xh = $("#xh", el), xd = $("#xd", el);
  hit.onmousemove = (e) => {
    const r = s.getBoundingClientRect(), mx = ((e.clientX - r.left) / r.width) * W;
    let i = 0; pts.forEach((p, j) => { if (Math.abs(p[0] - mx) < Math.abs(pts[i][0] - mx)) i = j; });
    xh.setAttribute("x1", pts[i][0]); xh.setAttribute("x2", pts[i][0]); xh.setAttribute("visibility", "visible");
    xd.setAttribute("cx", pts[i][0]); xd.setAttribute("cy", pts[i][1]); xd.setAttribute("visibility", "visible");
    showTip(e, `<b>${data[i].label}</b>` + tipRows([["#2a78d6", "Điểm", fmt(data[i].v)]]));
  };
  hit.onmouseleave = () => { hideTip(); xh.setAttribute("visibility", "hidden"); xd.setAttribute("visibility", "hidden"); };
}
window.addEventListener("resize", () => { clearTimeout(window._rz); window._rz = setTimeout(() => S.page === "dashboard" && renderDashboard(), 150); });

// ===================================================================== tài khoản
function renderProfiles() {
  const tb = $("#profile-table tbody");
  if (!S.profiles.length) {
    tb.innerHTML = `<tr><td colspan="8" class="empty-note">Chưa có tài khoản. Bấm <b>Thêm tài khoản</b>, rồi <b>Đăng nhập</b> một lần.</td></tr>`;
  } else {
    tb.innerHTML = S.profiles.map((p) => {
      const s = st(p.name), run = S.running.has(p.name);
      return `<tr data-name="${esc(p.name)}">
        <td><span class="avatar" data-run="${run ? 1 : 0}">${esc(initials(p.name))}</span></td>
        <td><b>${esc(p.name)}</b></td>
        <td>${p.mode === "cdp" ? `Edge đang mở · cổng ${p.cdp_port}` : "Cửa sổ riêng"}</td>
        <td>${statePill(p.name)}</td>
        <td class="r">${fmt(s.points)}</td>
        <td class="r">${s.today != null ? "+" + fmt(s.today) : "—"}</td>
        <td class="muted">${esc(s.progress || "")}</td>
        <td><div class="row-actions">
          ${run ? `<button class="btn small danger" data-act="stop">Dừng</button>`
                : `<button class="btn small primary" data-act="run">Chạy</button>
                   <button class="btn small ghost" data-act="login">Đăng nhập</button>
                   <button class="btn small ghost" data-act="edit">Sửa</button>
                   <button class="btn small ghost" data-act="del">Xóa</button>`}
        </div></td></tr>`;
    }).join("");
    $$("button[data-act]", tb).forEach((b) => (b.onclick = async () => {
      const name = b.closest("tr").dataset.name;
      const act = b.dataset.act;
      if (act === "run") start([name], "run");
      else if (act === "login") start([name], "login");
      else if (act === "stop") { await api().stop([name]); toast("Đang dừng " + name); }
      else if (act === "edit") openProfileDialog(S.profiles.find((p) => p.name === name));
      else if (act === "del" && confirm(`Xóa tài khoản "${name}" khỏi app?\nPhiên đăng nhập trong data/profiles vẫn được giữ.`)) {
        const r = await api().delete_profiles([name]); S.profiles = r.profiles;
        if (S.selected === name) S.selected = S.profiles[0]?.name ?? null;
        renderAll();
      }
    }));
  }
  renderToggles();
  $("#max-parallel").value = S.settings.max_parallel;
}

function renderToggles() {
  const ic = st(S.selected).icons || {};
  const any = (k) => Object.values(S.pstate).map((s) => (s.icons || {})[k]).find(Boolean);
  const items = [
    ["do_quests", "Daily Set, Keep earning", "Bấm từng thẻ task, làm quiz và poll", ic["Daily Set"] || any("Daily Set")],
    ["do_pc", "Search PC", "Tìm đến khi đủ điểm search máy tính", ic["Tìm kiếm"] || any("Tìm kiếm")],
    ["do_mobile", "Search Mobile", "Giả lập điện thoại, tìm đến khi đủ điểm", ic["Mobile"] || any("Mobile")],
    ["do_images", "Search ảnh", "Tìm trên Bing Images, mở xem ảnh", ic["Visual Search"] || any("Visual Search")],
    ["do_browse", "Browse", `Lướt web ${S.settings.browse_minutes} phút`,
      '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3"/></svg>'],
    ["headless", "Chạy ẩn", "Không hiện cửa sổ trình duyệt",
      '<svg viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 6.2A9.6 9.6 0 0 1 12 6c5 0 8.5 4.5 9.5 6-.5.8-1.6 2.3-3.2 3.6M6.2 7.6C4.3 9 3 11 2.5 12c1 1.5 4.5 6 9.5 6 1.6 0 3-.4 4.3-1.1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>'],
  ];
  $("#task-toggles").innerHTML = items.map(([k, t, d, img]) => `
    <label class="toggle">${!img ? `<span class="ico"></span>` : img.startsWith("<svg") ? `<span class="ico">${img}</span>` : `<img src="${esc(safeImg(img))}" alt="">`}
      <div><div class="tt">${t}</div><div class="td">${d}</div></div>
      <input type="checkbox" data-key="${k}" ${S.settings[k] ? "checked" : ""}></label>`).join("");
  $$("#task-toggles input").forEach((i) => (i.onchange = () => saveSettings({ [i.dataset.key]: i.checked })));
}

async function saveSettings(partial) {
  const r = await api().save_settings(partial);
  S.settings = r.settings;
  if (!r.ok) toast(r.error);
  return r.ok;
}

function bindProfileDialog() {
  const dlg = $("#profile-dialog"), f = $("#profile-form");
  const syncPort = () => ($("#pd-port").hidden = f.mode.value !== "cdp");
  $$("input[name=mode]", f).forEach((r) => (r.onchange = syncPort));
  f.onsubmit = async (e) => {
    if (e.submitter?.value !== "ok") return;
    e.preventDefault();
    const r = await api().save_profile(dlg.dataset.old || null,
      { name: f.name.value, mode: f.mode.value, cdp_port: +f.cdp_port.value });
    if (!r.ok) { $("#pd-error").textContent = r.error; return; }
    if (S.selected === dlg.dataset.old || !S.selected) S.selected = f.name.value.trim();
    S.profiles = r.profiles; dlg.close(); renderAll();
    toast(dlg.dataset.old ? "Đã lưu tài khoản" : "Đã thêm tài khoản. Bấm Đăng nhập để đăng nhập lần đầu.");
  };
  dlg._sync = syncPort;
}

function openProfileDialog(p) {
  const dlg = $("#profile-dialog"), f = $("#profile-form");
  dlg.dataset.old = p ? p.name : "";
  $("#pd-title").textContent = p ? "Sửa tài khoản" : "Thêm tài khoản";
  f.name.value = p ? p.name : `Tài khoản ${S.profiles.length + 1}`;
  f.mode.value = p ? p.mode : "managed";
  f.cdp_port.value = p ? p.cdp_port : 9222 + S.profiles.length;
  $("#pd-error").textContent = "";
  dlg._sync(); dlg.showModal(); f.name.select();
}
window.openProfileDialog = openProfileDialog; window.go = go;

// ===================================================================== nhật ký
function renderLog() {
  const sel = $("#log-filter"), cur = sel.value || "";
  sel.innerHTML = `<option value="">Tất cả tài khoản</option>` + S.profiles.map((p) => `<option ${p.name === cur ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  const box = $("#logbox"); box.innerHTML = "";
  S.logs.filter((l) => !cur || l.name === cur).slice(-1500).forEach(appendLog);
  if (!S.logs.length) box.innerHTML = `<div class="l tm">Chưa có nhật ký. Khi bot chạy, từng bước sẽ hiện ở đây.</div>`;
}
function appendLog(e) {
  const cur = $("#log-filter").value;
  if (cur && e.name !== cur) return;
  const box = $("#logbox"), atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const d = document.createElement("div");
  d.className = "l";
  d.innerHTML = `<span class="tm">${esc(e.time)}</span> <span class="nm">${esc(e.name)}</span> <span class="${/^\s*(lỗi|cảnh báo)/i.test(e.msg) ? "er" : ""}">${esc(e.msg)}</span>`;
  box.appendChild(d);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

// ===================================================================== cài đặt
const SETTING_FIELDS = [
  ["search_delay_min", "Nghỉ ít nhất giữa 2 lượt search (giây)"],
  ["search_delay_max", "Nghỉ nhiều nhất giữa 2 lượt search (giây)"],
  ["extra_searches", "Số lượt search thêm cho chắc đủ điểm"],
  ["image_searches", "Số lượt search ảnh"],
  ["browse_minutes", "Thời gian browse (phút)"],
  ["history_days", "Không lặp lại câu search đã dùng trong (ngày)"],
];
function renderSettings() {
  $("#settings-form").innerHTML = SETTING_FIELDS.map(([k, l]) =>
    `<label for="set-${k}">${l}</label><input type="number" min="0" id="set-${k}" data-key="${k}" value="${esc(S.settings[k])}">`).join("")
    + `<label for="set-browser">Trình duyệt cho cửa sổ riêng</label>
       <select id="set-browser">${[["msedge", "Microsoft Edge"], ["chrome", "Google Chrome"], ["", "Chromium"]]
        .map(([v, t]) => `<option value="${v}" ${S.settings.browser_channel === v ? "selected" : ""}>${t}</option>`).join("")}</select>
       <label for="set-bypass-proxy">Không đi qua proxy hệ thống (chặn proxy chen giữa)</label>
       <input type="checkbox" id="set-bypass-proxy" ${S.settings.bypass_proxy !== false ? "checked" : ""}>`;
}
async function saveSettingsForm() {
  const partial = { browser_channel: $("#set-browser").value };
  for (const i of $$("#settings-form input[data-key]")) {
    const v = parseInt(i.value, 10);
    if (Number.isNaN(v) || v < 0) { toast("Ô “" + i.previousElementSibling.textContent + "” cần là số không âm"); i.focus(); return; }
    partial[i.dataset.key] = v;
  }
  partial.bypass_proxy = $("#set-bypass-proxy").checked;
  const ok = await saveSettings(partial);
  renderSettings();
  if (ok) toast("Đã lưu cài đặt");
}
