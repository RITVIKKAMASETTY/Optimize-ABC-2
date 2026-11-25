"use strict";
/* Upload & fit page. Helpers and charts come from charts.js. */
let UP = null, RES = null, PICK = "avg";

const ROLES = [
  ["voltage", "O₂ path voltage", "Voltage across the resistor", true, [["V","V"],["mV","mV"],["uV","µV"]]],
  ["resistance", "Resistance", "Used for I = V / R", true, [["ohm","Ω"],["kohm","kΩ"],["Mohm","MΩ"]]],
  ["pressure", "Pressure", "Gas pressure", true, [["kPa","kPa"],["Pa","Pa"],["bar","bar"],["mbar","mbar"],["atm","atm"],["psi","psi"],["Torr","Torr"]]],
  ["concentration", "Known O₂ concentration", "The value to match", true, [["%","%"],["fraction","fraction 0–1"],["ppm","ppm"]]],
  ["temperature", "Temperature", "For the physics; empty = fixed value", false, [["C","°C"],["K","K"]]],
];
const CONSTS = [["T_fixed","Fixed temperature","K"],["a","Pore radius a","m"],["S","Cross-section S","m²"],["L","Thickness L","m"],
  ["M","O₂ molar mass M","kg/mol"],["D0","Diffusivity D0","m²/s"],["alpha","Temperature exponent α","—"],["P0","Reference pressure P0","Pa"]];
const MCOL = {theory:"#6e6e6e", A_only:"#3987e5", B_only:"#199e70", AB:"#d95926", K:"#c98500", avg:"#ededed"};
const SHORT = {theory:"Theory", A_only:"1 · A", B_only:"2 · B", AB:"3 · A, B", K:"4 · K", avg:"Average"};
const FACT = {voltage:{V:1,mV:1e-3,uV:1e-6}, resistance:{ohm:1,kohm:1e3,Mohm:1e6},
  pressure:{Pa:1,kPa:1e3,bar:1e5,mbar:100,atm:101325,psi:6894.757,Torr:133.322}};
function card(id, title, desc, h){ return `<div class="card"><div class="card-h"><h3>${title}</h3></div><p class="desc">${desc}</p><div id="${id}" style="min-height:${h||260}px"></div></div>`; }

function setStep(n){   // n = highest unlocked step
  document.querySelectorAll("#stepper li").forEach((li,i) => {
    li.className = i+1 < n ? "done" : i+1 === n ? "on" : "locked"; });
}

/* ---------- 1 · upload ---------- */
const fileEl = $("#file"), drop = $("#drop");
fileEl.onchange = () => { if (fileEl.files[0]) upload(fileEl.files[0]); fileEl.value = ""; };
["dragover","dragenter"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("on"); }));
["dragleave","drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("on"); }));
drop.addEventListener("drop", ev => ev.dataTransfer.files[0] && upload(ev.dataTransfer.files[0]));

async function upload(file){
  $("#upErr").textContent = "";
  const fd = new FormData(); fd.append("file", file);
  try { showTable(await api("/api/upload", {method:"POST", body:fd})); }
  catch(e){ $("#upErr").textContent = e.message; }
}
async function reparse(){
  try { showTable(await api("/api/upload", {method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({sheet:$("#sheet").value, header_row:Number($("#hdr").value)||1})})); }
  catch(e){ $("#upErr").textContent = e.message; }
}
$("#sheet").onchange = reparse; $("#hdr").onchange = reparse;

function showTable(t){
  UP = t; RES = null;
  drop.classList.add("hidden"); $("#fileBar").classList.remove("hidden");
  $("#fileExt").textContent = (t.filename.split(".").pop() || "").toUpperCase().slice(0,4);
  $("#fileName").textContent = t.filename;
  $("#fileMeta").textContent = `${t.n_rows} rows · ${t.columns.length} columns${t.sheet ? " · sheet " + t.sheet : ""}`;
  $("#status").innerHTML = `<i style="background:var(--warn)"></i>${esc(t.filename)}`;
  $("#sheetBox").classList.remove("hidden");
  $("#sheetField").classList.toggle("hidden", !t.sheets.length);
  $("#sheet").innerHTML = t.sheets.map(s => `<option${s===t.sheet?" selected":""}>${esc(s)}</option>`).join("");
  $("#hdr").value = t.header_row; $("#nrows").value = t.n_rows;
  $("#preview").innerHTML = `<thead><tr>${t.columns.map(c=>`<th class="l">${esc(c)}</th>`).join("")}</tr></thead><tbody>${
    t.preview.map(r=>`<tr>${r.map(v=>`<td class="l">${v===null?"":esc(typeof v==="number"?fmt(v,6):v)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  buildForm();
  ["#results","#predict"].forEach(s => $(s).classList.add("hidden"));
  $("#columns").classList.remove("hidden");
  setStep(2);
}

/* ---------- 2 · columns, filters, constants ---------- */
const memKey = () => "o2fit:" + UP.columns.join("|");
function colOptions(sel, emptyLabel){
  return `<option value="">${emptyLabel}</option>` + UP.columns.map((c,i) =>
    `<option value="${esc(c)}"${c===sel?" selected":""}>${esc(c)}${UP.numeric[i] < UP.n_rows ? ` · ${UP.numeric[i]} numbers` : ""}</option>`).join("");
}
function buildForm(){
  const mem = JSON.parse(localStorage.getItem(memKey()) || "null") || {};
  const m = mem.mapping || {}, u = mem.units || {};
  $("#map").innerHTML = ROLES.map(([k,label,hint,req,units]) => `<div class="maprow" data-row="${k}">
      <div class="lab">${label}${req ? "" : '<span class="tag">optional</span>'}<small>${hint}</small></div>
      <div class="inp"><select data-role="${k}">${colOptions(m[k], req ? "Choose a column…" : "None — use fixed temperature")}</select></div>
      <div class="inp"><select data-unit="${k}">${units.map(([v,t])=>`<option value="${v}"${u[k]===v?" selected":""}>${t}</option>`).join("")}</select></div></div>`).join("");
  document.querySelectorAll("[data-role]").forEach(s => s.addEventListener("change", () => s.closest(".maprow").classList.remove("miss")));
  $("#filters").innerHTML = "";
  (mem.filters && mem.filters.length ? mem.filters : [{column:"", op:">", value:495}]).forEach(addFilter);
  const cst = {...UP.constants, ...(mem.constants||{})};
  $("#consts").innerHTML = CONSTS.map(([k,l,un]) => `<div class="field"><label class="f">${l}</label><div class="inp"><input data-const="${k}" type="number" step="any" value="${cst[k]}"><span class="unit">${un}</span></div></div>`).join("");
}
function addFilter(f){
  f = f || {column:"", op:">", value:""};
  const row = document.createElement("div"); row.className = "frow";
  row.innerHTML = `<span class="w">${$("#filters").children.length ? "and" : "where"}</span>
    <div class="inp"><select data-f="column">${colOptions(f.column, "No filter")}</select></div>
    <div class="inp"><select data-f="op">${UP.ops.map(o=>`<option${o===f.op?" selected":""}>${o}</option>`).join("")}</select></div>
    <div class="inp"><input data-f="value" type="number" step="any" value="${f.value}" placeholder="value"></div>
    <button class="x" type="button" title="Remove filter">×</button>`;
  row.querySelector(".x").onclick = () => { row.remove(); const first = $("#filters .w"); if (first) first.textContent = "where"; };
  $("#filters").appendChild(row);
}
$("#addFilter").onclick = () => addFilter();

function readForm(){
  const mapping = {}, units = {}, constants = {};
  document.querySelectorAll("[data-role]").forEach(s => { if (s.value) mapping[s.dataset.role] = s.value; });
  document.querySelectorAll("[data-unit]").forEach(s => units[s.dataset.unit] = s.value);
  document.querySelectorAll("[data-const]").forEach(i => constants[i.dataset.const] = Number(i.value));
  const filters = [...document.querySelectorAll(".frow")].map(r => ({column:r.querySelector('[data-f="column"]').value,
    op:r.querySelector('[data-f="op"]').value, value:r.querySelector('[data-f="value"]').value})).filter(f => f.column && f.value !== "");
  return {mapping, units, constants, filters};
}

$("#run").onclick = async () => {
  const body = readForm();
  const missing = ROLES.filter(r => r[3] && !body.mapping[r[0]]);
  missing.forEach(r => $(`[data-row="${r[0]}"]`).classList.add("miss"));
  if (missing.length){ $("#runMsg").textContent = "Choose a column for: " + missing.map(r=>r[1]).join(", "); return; }
  localStorage.setItem(memKey(), JSON.stringify(body));
  $("#run").disabled = true; $("#runMsg").textContent = "Optimizing…";
  try {
    RES = await api("/api/fit", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    $("#runMsg").textContent = `Done · ${RES.data.C.length} rows fitted`; PICK = "avg";
    showResults(); buildPredict(); setStep(4);
    $("#status").innerHTML = `<i style="background:var(--good)"></i>${esc(RES.filename)} · ${RES.data.C.length} rows`;
    $("#results").scrollIntoView({behavior:"smooth"});
  } catch(e){ $("#runMsg").textContent = e.message; }
  $("#run").disabled = false;
};

/* ---------- 3 · results ---------- */
function showResults(){
  const r = RES, M = Object.fromEntries(r.models.map(m => [m.key, m])), four = ["A_only","B_only","AB","K"].map(k => M[k]);
  const best = four.reduce((a,b) => a.metrics.RMSE <= b.metrics.RMSE ? a : b);
  $("#results").classList.remove("hidden");
  $("#resSub").textContent = `${r.filename} · ${r.data.C.length} rows · known O₂ ${fmt(r.ranges.C[0],3)}–${fmt(r.ranges.C[1],3)} %`;
  $("#resBody").innerHTML = `
    <div class="funnel">${r.steps.map(s => `<span>${esc(s.step)} <b>${s.rows}</b></span>`).join("")}</div>
    <div class="tiles">
      <div class="tile"><div class="t">A_avg</div><div class="v">${fmt(M.avg.A,4)}</div><div class="s">mean of 4 conditions</div></div>
      <div class="tile"><div class="t">B_avg</div><div class="v">${fmt(M.avg.B,4)}</div><div class="s">mean of 4 conditions</div></div>
      <div class="tile"><div class="t">RMSE · average model</div><div class="v">${fx(M.avg.metrics.RMSE,2)} %</div><div class="s">R² ${fx(M.avg.metrics.R2,3)}</div></div>
      <div class="tile"><div class="t">Lowest RMSE of 1–4</div><div class="v">${fx(best.metrics.RMSE,2)} %</div><div class="s">${esc(best.label.slice(3))}</div></div>
    </div>
    <p class="sub-h">The four conditions</p>
    <div class="eq">C = 100·[1 − exp(−(I·R·T·L / 4·F·S·P)·(A/Dk + B/Db))] &nbsp;&nbsp; I = V / R</div>
    <ul class="conds">
      <li><a href="/condition/A_only"><span>details →</span><b>1 · Optimize A, B = 1</b><code>A = ${fmt(M.A_only.A,4)}</code></a></li>
      <li><a href="/condition/B_only"><span>details →</span><b>2 · Optimize B, A = 1</b><code>B = ${fmt(M.B_only.B,4)}</code></a></li>
      <li><a href="/condition/AB"><span>details →</span><b>3 · Optimize A and B</b><code>A = ${fmt(M.AB.A,4)}, B = ${fmt(M.AB.B,4)}</code></a></li>
      <li><a href="/condition/K"><span>details →</span><b>4 · K/Deff = 1/Dk + 1/Db</b><code>K = ${fmt(M.K.A,4)}</code> (A = B = K)</a></li>
    </ul>
    <div class="eq">A_avg = (${four.map(m=>fmt(m.A,4)).join(" + ")}) / 4 = ${fmt(M.avg.A,4)}<br>B_avg = (${four.map(m=>fmt(m.B,4)).join(" + ")}) / 4 = ${fmt(M.avg.B,4)}</div>
    <p class="hint">Each condition minimizes Σ(C_predicted − C_known)² over the rows (Levenberg–Marquardt, started from the straight-line least-squares solution).</p>
    <div class="tbl" style="margin:18px 0"><table>
      <thead><tr><th class="l">Model (click a row for every detail)</th><th>A</th><th>B</th><th>RMSE %</th><th>MAE %</th><th>Max |error| %</th><th>Bias %</th><th>R²</th><th></th></tr></thead>
      <tbody>${r.models.map(m=>`<tr class="click ${m.key==="avg"?"best":""}" data-href="/condition/${m.key}"><td class="l"><span class="sw" style="background:${MCOL[m.key]}"></span>${esc(m.label)}</td>
        <td>${fmt(m.A,5)}</td><td>${fmt(m.B,5)}</td><td>${fx(m.metrics.RMSE,3)}</td><td>${fx(m.metrics.MAE,3)}</td><td>${fx(m.metrics.MaxAE,2)}</td>
        <td>${fx(m.metrics.Bias,3)}</td><td>${fx(m.metrics.R2,4)}</td><td><span class="go">details →</span></td></tr>`).join("")}</tbody></table></div>
    <div class="grid g2">
      ${card("chRmse","Error by model","RMSE and MAE of every model.")}
      <div class="card"><div class="card-h"><h3>Known vs predicted</h3>
        <div class="inp mini"><select id="pick">${r.models.map(m=>`<option value="${m.key}"${m.key===PICK?" selected":""}>${esc(SHORT[m.key])}</option>`).join("")}</select></div></div>
        <p class="desc">Each point is one row; on the dashed line prediction = known.</p><div id="chParity" style="min-height:260px"></div></div>
      ${card("chRes","Error vs pressure","Predicted − known, for the model chosen above.")}
      ${r.models[0].per_level ? card("chLevel","Mean absolute error per concentration","Theory, A and B together, and the average.") : card("chResC","Error vs known concentration","Predicted − known, for the model chosen above.")}
    </div>`;
  $("#pick").onchange = e => { PICK = e.target.value; drawPicked(); };
  document.querySelectorAll("tr.click").forEach(tr => tr.onclick = () => location.href = tr.dataset.href);
  $("#dl").onclick = downloadCsv;
  bars($("#chRmse"), {xlabel:"model", ylabel:"error (% O₂)", series:[{name:"RMSE", color:"#ededed"},{name:"MAE", color:"#6e6e6e"}],
    groups:r.models.map(m=>({label:SHORT[m.key], values:[m.metrics.RMSE, m.metrics.MAE]}))});
  if (r.models[0].per_level){
    const lv = M.theory.per_level.map(x=>x.C);
    bars($("#chLevel"), {xlabel:"known O₂ (%)", ylabel:"MAE (% O₂)",
      series:[{name:"Theory",color:MCOL.theory},{name:"A and B",color:MCOL.AB},{name:"Average",color:MCOL.avg}],
      groups:lv.map((c,i)=>({label:fmt(c,3), values:[M.theory.per_level[i].MAE, M.AB.per_level[i].MAE, M.avg.per_level[i].MAE]}))});
  }
  drawPicked();
}
function drawPicked(){
  const r = RES, m = r.models.find(x => x.key === PICK), d = r.data;
  const lo = Math.min(...d.C, ...m.pred), hi = Math.max(...d.C, ...m.pred), pad = (hi-lo)*0.05 || 1;
  const tip = p => [`row ${p[2]} · known ${fmt(p[3],4)} %`, `predicted ${fx(p[4],2)} % · error ${fx(p[4]-p[3],2)}`, `P ${fmt(p[5],4)} kPa · I ${fmt(p[6],4)} µA`];
  const pts = f => d.C.map((c,i)=>[...f(c,i), d.row[i], c, m.pred[i], d.P_kPa[i], d.I_uA[i]]);
  plot($("#chParity"), {height:260, x:{label:"known O₂ (%)", min:lo-pad, max:hi+pad}, y:{label:"predicted O₂ (%)", min:lo-pad, max:hi+pad}, legend:false,
    series:[{name:"", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[-10,-10],[110,110]]},
      {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[c, m.pred[i]])}], tip});
  const zero = {name:"", type:"line", color:"#555", width:1, noHover:true, noExtent:true, hideLegend:true, pts:[[-1e6,0],[1e6,0]]};
  plot($("#chRes"), {height:260, x:{label:"pressure (kPa)"}, y:{label:"predicted − known (%)"}, legend:false,
    series:[zero, {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[d.P_kPa[i], m.pred[i]-c])}], tip});
  if ($("#chResC")) plot($("#chResC"), {height:260, x:{label:"known O₂ (%)"}, y:{label:"predicted − known (%)"}, legend:false,
    series:[zero, {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[c, m.pred[i]-c])}], tip});
}
function downloadCsv(){
  const r = RES, d = r.data;
  const head = ["row","voltage_V","resistance_ohm","I_uA","P_kPa","T_K","C_known", ...r.models.map(m=>"C_"+m.key)];
  const lines = [head.join(",")].concat(d.C.map((c,i)=>[d.row[i], d.V[i], d.R[i], d.I_uA[i], d.P_kPa[i], d.T_K[i], c, ...r.models.map(m=>m.pred[i])].join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")], {type:"text/csv"}));
  a.download = r.filename.replace(/\.[^.]+$/, "") + "_predictions.csv"; a.click();
}

/* ---------- 4 · predict ---------- */
function buildPredict(){
  const r = RES, d = r.data, u = r.units;
  const lab = k => (ROLES.find(x=>x[0]===k)[4].find(x=>x[0]===u[k])||[,""])[1];
  const f = (id,label,unit,val) => `<div class="field"><label class="f" for="${id}">${label}</label><div class="inp big-in"><input id="${id}" type="number" step="any" value="${val}"><span class="unit">${unit}</span></div></div>`;
  const p6 = v => +v.toPrecision(6);
  $("#predForm").innerHTML = f("pV","O₂ path voltage",lab("voltage"), p6(d.V[0]/FACT.voltage[u.voltage]))
    + f("pR","Resistance",lab("resistance"), p6(d.R[0]/FACT.resistance[u.resistance]))
    + f("pP","Pressure",lab("pressure"), p6(d.P_kPa[0]*1e3/FACT.pressure[u.pressure]))
    + (r.uses_T_column ? f("pT","Temperature",lab("temperature"), p6(u.temperature==="C" ? d.T_K[0]-273.15 : d.T_K[0])) : "")
    + `<div class="field"><label class="f" for="pM">Model</label><div class="inp big-in"><select id="pM">${r.models.map(m=>`<option value="${m.key}"${m.key==="avg"?" selected":""}>${esc(m.label)}</option>`).join("")}</select></div></div>
       <p class="hint">Filled with the first fitted row (known value ${fmt(d.C[0],4)} %).</p>`;
  let t; const go = () => { clearTimeout(t); t = setTimeout(doPredict, 150); };
  $("#predForm").querySelectorAll("input,select").forEach(e => e.addEventListener("input", go));
  $("#predict").classList.remove("hidden"); doPredict();
}
async function doPredict(){
  const body = {V:$("#pV").value, R:$("#pR").value, P:$("#pP").value, T:$("#pT") ? $("#pT").value : null};
  try {
    const p = await api("/api/predict", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    const key = $("#pM").value, m = p.models.find(x => x.key === key);
    $("#predC").innerHTML = `${fx(m.C,2)}<small>% O₂</small>`;
    $("#predPill").textContent = SHORT[key];
    $("#predSub").textContent = `I = V / R = ${fmt(p.I_uA,5)} µA · P = ${fmt(p.P_kPa,5)} kPa · T = ${fmt(p.T_K,5)} K`;
    $("#predAll").innerHTML = `<thead><tr><th class="l">Model</th><th>C (%)</th></tr></thead><tbody>${p.models.map(x =>
      `<tr class="${x.key===key?"best":""}"><td class="l"><span class="sw" style="background:${MCOL[x.key]}"></span>${esc(x.label)}</td><td>${fx(x.C,3)}</td></tr>`).join("")}</tbody>`;
  } catch(e){ $("#predSub").textContent = e.message; $("#predC").textContent = "—"; }
}

/* ---------- restore what is loaded (after Back from a detail page, or a reload) ---------- */
api("/api/state").then(st => {
  if (!st.table) return;
  showTable(st.table);
  if (st.result){
    RES = st.result; PICK = "avg";
    $("#runMsg").textContent = `${RES.data.C.length} rows fitted`;
    showResults(); buildPredict(); setStep(4);
    $("#status").innerHTML = `<i style="background:var(--good)"></i>${esc(RES.filename)} · ${RES.data.C.length} rows`;
    if (location.hash) setTimeout(() => { const el = $(location.hash); if (el) el.scrollIntoView(); }, 250);
  }
}).catch(() => {});
