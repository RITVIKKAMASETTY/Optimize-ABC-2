"use strict";
/* Detail page for one condition: every row, per-concentration breakdown, how the fit was found. */
const KEY = decodeURIComponent(location.pathname.split("/").pop());
const MCOL = {theory:"#6e6e6e", A_only:"#3987e5", B_only:"#199e70", AB:"#d95926", K:"#c98500", avg:"#ededed"};
const SHORT = {theory:"Theory", A_only:"1 · Optimize A", B_only:"2 · Optimize B", AB:"3 · Optimize A, B", K:"4 · Optimize K", avg:"Average"};
const WHAT = {
  theory: ["Nothing is optimized: A = B = 1 (the textbook Bosanquet combination).", "1/Deff = 1/Dk + 1/Db"],
  A_only: ["Only A is optimized; B is fixed at 1.", "1/Deff = A/Dk + 1/Db"],
  B_only: ["Only B is optimized; A is fixed at 1.", "1/Deff = 1/Dk + B/Db"],
  AB: ["A and B are optimized together.", "1/Deff = A/Dk + B/Db"],
  K: ["One factor K multiplies the whole Bosanquet sum (A = B = K).", "K/Deff = 1/Dk + 1/Db   ⇔   1/Deff = K/Dk + K/Db"],
  avg: ["A and B are the averages of conditions 1–4. Nothing is optimized directly.", "1/Deff = A_avg/Dk + B_avg/Db"],
};
let RES = null, M = null, SORT = {col:"row", dir:1}, MINERR = 0;
function card(id, title, desc, h){ return `<div class="card"><div class="card-h"><h3>${title}</h3></div><p class="desc">${desc}</p><div id="${id}" style="min-height:${h||260}px"></div></div>`; }

api("/api/state").then(s => {
  RES = s.result;
  if (!RES){ $("#app").innerHTML = `<div class="panel"><div class="panel-b"><p>No results yet. <a href="/">Upload a file and run the optimizations</a> first.</p></div></div>`; return; }
  M = RES.models.find(m => m.key === KEY);
  $("#tabs").innerHTML = RES.models.map(m => `<a href="/condition/${m.key}" class="${m.key===KEY?"on":""}"><i style="background:${MCOL[m.key]}"></i>${SHORT[m.key]}</a>`).join("");
  if (!M){ $("#app").innerHTML = `<p>Unknown condition. Pick one above.</p>`; return; }
  document.title = `Zirconia O₂ · ${M.label}`;
  render();
}).catch(e => $("#app").innerHTML = `<p class="err">${esc(e.message)}</p>`);

function render(){
  const r = RES, d = r.data, m = M, mt = m.metrics, n = d.C.length;
  const err = d.C.map((c,i) => m.pred[i] - c);
  const others = Object.fromEntries(r.models.map(x => [x.key, x]));
  let how = "";
  if (m.fit){
    const f = m.fit, last = f.steps[f.steps.length-1];
    how = `<p class="note">The optimizer minimizes <b>Σ (C_predicted − C_known)²</b> over the ${n} rows.
        It starts from the straight-line least-squares solution of −ln(1 − C/100) = A·p + B·q
        (A = ${fmt(f.linear_A,5)}, B = ${fmt(f.linear_B,5)}) and from the theory point (1, 1), runs Levenberg–Marquardt from both,
        and keeps the better one. Kept: <b>${esc(f.start_used)}</b>, ${f.steps.length-1} steps, SSE ${fmt(f.steps[0].SSE,6)} → ${fmt(last.SSE,6)}.</p>
      <div class="grid g2" style="margin-top:14px">
        <div class="tbl" style="max-height:300px"><table><thead><tr><th class="l">Step</th><th>A</th><th>B</th><th>SSE</th><th>RMSE %</th></tr></thead>
          <tbody>${f.steps.map(s => `<tr><td class="l">${s.it}</td><td>${fmt(s.A,6)}</td><td>${fmt(s.B,6)}</td><td>${fmt(s.SSE,6)}</td><td>${fx(s.RMSE,4)}</td></tr>`).join("")}</tbody></table></div>
        <div class="card"><div id="chConv" style="min-height:220px"></div></div>
      </div>`;
  } else if (m.key === "avg"){
    const four = ["A_only","B_only","AB","K"].map(k => others[k]);
    how = `<p class="note">Nothing is fitted here. A and B are the plain averages of the four optimized conditions:</p>
      <div class="tbl" style="margin:12px 0"><table><thead><tr><th class="l">Condition</th><th>A</th><th>B</th><th>RMSE %</th></tr></thead><tbody>
        ${four.map(x => `<tr><td class="l"><a href="/condition/${x.key}">${esc(x.label)}</a></td><td>${fmt(x.A,5)}</td><td>${fmt(x.B,5)}</td><td>${fx(x.metrics.RMSE,3)}</td></tr>`).join("")}
        <tr class="best"><td class="l">Average</td><td>${fmt(m.A,5)}</td><td>${fmt(m.B,5)}</td><td>${fx(mt.RMSE,3)}</td></tr></tbody></table></div>
      <div class="eq">A_avg = (${four.map(x=>fmt(x.A,4)).join(" + ")}) / 4 = ${fmt(m.A,5)}<br>B_avg = (${four.map(x=>fmt(x.B,4)).join(" + ")}) / 4 = ${fmt(m.B,5)}</div>`;
  } else {
    how = `<p class="note">Nothing is optimized. This is the textbook model, shown as the baseline the other conditions improve on.</p>`;
  }

  const lv = m.per_level;
  $("#app").innerHTML = `
    <div class="hero">
      <p class="eyebrow-s"><span class="sw" style="background:${MCOL[m.key]}"></span>${esc(r.filename)} · ${n} rows</p>
      <h1>${esc(m.label)}</h1>
      <p>${WHAT[m.key][0]}</p>
      <div class="eq" style="max-width:640px">${WHAT[m.key][1]}</div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="t">A</div><div class="v">${fmt(m.A,5)}</div><div class="s">${["theory","B_only"].includes(m.key)?"fixed":"result"}</div></div>
      <div class="tile"><div class="t">B</div><div class="v">${fmt(m.B,5)}</div><div class="s">${["theory","A_only"].includes(m.key)?"fixed":"result"}</div></div>
      <div class="tile"><div class="t">RMSE</div><div class="v">${fx(mt.RMSE,3)} %</div><div class="s">R² ${fx(mt.R2,4)}</div></div>
      <div class="tile"><div class="t">MAE · max |error|</div><div class="v">${fx(mt.MAE,3)} %</div><div class="s">max ${fx(mt.MaxAE,2)} % · bias ${fx(mt.Bias,3)}</div></div>
      <div class="tile"><div class="t">Rows within ±1 / ±2 / ±5 %</div><div class="v" style="font-size:19px;margin-top:10px">${fx(mt.within1,0)} / ${fx(mt.within2,0)} / ${fx(mt.within5,0)} %</div><div class="s">of ${n} rows</div></div>
    </div>

    <section class="panel"><div class="panel-h"><span class="num">A</span><div><h2>How this result was found</h2><p>Starting point, every optimizer step and the averaging, where it applies.</p></div></div>
      <div class="panel-b">${how}</div></section>

    <section class="panel"><div class="panel-h"><span class="num">B</span><div><h2>Per known concentration</h2>
      <p>${lv ? `${lv.length} concentration levels. For each: how many rows, and the average, lowest and highest prediction.` : "More than 30 different concentration values, so they are not grouped. See the row table below."}</p></div></div>
      <div class="panel-b">${lv ? `
        <div class="tbl" style="margin-bottom:16px"><table><thead><tr><th class="l">Known O₂ %</th><th>Rows</th><th>Mean predicted</th><th>Lowest</th><th>Highest</th><th>Mean error</th><th>MAE</th><th>RMSE</th></tr></thead>
          <tbody>${lv.map(x => `<tr><td class="l">${fmt(x.C,4)}</td><td>${x.n}</td><td>${fx(x.mean_pred,3)}</td><td>${fx(x.min_pred,3)}</td><td>${fx(x.max_pred,3)}</td>
            <td class="${Math.abs(x.Bias)>2?"bad":""}">${x.Bias>=0?"+":""}${fx(x.Bias,3)}</td><td>${fx(x.MAE,3)}</td><td>${fx(x.RMSE,3)}</td></tr>`).join("")}</tbody></table></div>
        <div class="grid g2">${card("chLevel","Predicted range per concentration","Dot = mean prediction; the bar spans lowest to highest. On the dashed line prediction = known.")}
          ${card("chBias","Mean error per concentration","Above zero: predicted too high. Below zero: too low.")}</div>` : ""}
      </div></section>

    <section class="panel"><div class="panel-h"><span class="num">C</span><div><h2>Charts for all rows</h2><p>Hover a point to see the row.</p></div></div>
      <div class="panel-b"><div class="grid g2">
        ${card("chParity","Known vs predicted","Each point is one row.")}
        ${card("chRes","Error vs pressure","Predicted − known.")}
        ${card("chHist","How the errors are spread","Number of rows in each 1 % error band.")}
        ${card("chResC","Error vs known concentration","Predicted − known.")}
      </div></div></section>

    <section class="panel"><div class="panel-h"><span class="num">D</span><div><h2>Every row</h2><p>Click a column title to sort. Error = predicted − known.</p></div>
      <div class="act"><div class="inp" style="width:210px;height:34px"><input id="minErr" type="number" step="any" min="0" placeholder="show |error| ≥"><span class="unit">%</span></div>
        <button class="btn" id="dl" type="button">Download CSV</button></div></div>
      <div class="panel-b"><p class="hint" id="rowInfo"></p><div class="tbl" style="max-height:560px"><table id="rows"></table></div></div></section>`;

  if (m.fit) plot($("#chConv"), {height:220, x:{label:"step", fmt:v=>fmt(v,0)}, y:{label:"RMSE (%)"}, legend:false,
    series:[{name:"RMSE", type:"line", color:MCOL[m.key], pts:m.fit.steps.map(s=>[s.it, s.RMSE])},
            {name:"RMSE", type:"scatter", color:MCOL[m.key], r:3.5, pts:m.fit.steps.map(s=>[s.it, s.RMSE])}],
    tip:p=>[`step ${p[0]}`, `RMSE ${fx(p[1],4)} %`]});
  if (lv){
    const lo = Math.min(...lv.map(x=>Math.min(x.C,x.min_pred))), hi = Math.max(...lv.map(x=>Math.max(x.C,x.max_pred))), pad=(hi-lo)*0.05||1;
    plot($("#chLevel"), {x:{label:"known O₂ (%)", min:lo-pad, max:hi+pad}, y:{label:"predicted O₂ (%)", min:lo-pad, max:hi+pad}, legend:false,
      series:[{name:"", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[-10,-10],[110,110]]},
        ...lv.map(x => ({name:"range", type:"line", color:MCOL[m.key], width:2, opacity:.45, noHover:true, hideLegend:true, pts:[[x.C,x.min_pred],[x.C,x.max_pred]]})),
        {name:"mean", type:"scatter", color:MCOL[m.key], r:4.5, pts:lv.map(x=>[x.C, x.mean_pred, x.n, x.min_pred, x.max_pred])}],
      tip:p=>[`known ${fmt(p[0],4)} % · ${p[2]} rows`, `mean ${fx(p[1],2)} % · range ${fx(p[3],2)}–${fx(p[4],2)}`]});
    bars($("#chBias"), {xlabel:"known O₂ (%)", ylabel:"mean error (%)", series:[{name:"mean error", color:MCOL[m.key]}],
      groups:lv.map(x=>({label:fmt(x.C,3), values:[x.Bias]}))});
  }
  const lo = Math.min(...d.C, ...m.pred), hi = Math.max(...d.C, ...m.pred), pad = (hi-lo)*0.05||1;
  const tip = p => [`row ${p[2]} · known ${fmt(p[3],4)} %`, `predicted ${fx(p[4],2)} % · error ${fx(p[4]-p[3],2)}`, `P ${fmt(p[5],4)} kPa · I ${fmt(p[6],4)} µA`];
  const pts = f => d.C.map((c,i)=>[...f(c,i), d.row[i], c, m.pred[i], d.P_kPa[i], d.I_uA[i]]);
  const zero = {name:"", type:"line", color:"#555", width:1, noHover:true, noExtent:true, hideLegend:true, pts:[[-1e6,0],[1e6,0]]};
  plot($("#chParity"), {x:{label:"known O₂ (%)", min:lo-pad, max:hi+pad}, y:{label:"predicted O₂ (%)", min:lo-pad, max:hi+pad}, legend:false,
    series:[{name:"", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[-10,-10],[110,110]]},
      {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[c, m.pred[i]])}], tip});
  plot($("#chRes"), {x:{label:"pressure (kPa)"}, y:{label:"predicted − known (%)"}, legend:false,
    series:[zero, {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[d.P_kPa[i], m.pred[i]-c])}], tip});
  plot($("#chResC"), {x:{label:"known O₂ (%)"}, y:{label:"predicted − known (%)"}, legend:false,
    series:[zero, {name:m.label, type:"scatter", color:MCOL[m.key], r:3, pts:pts((c,i)=>[c, m.pred[i]-c])}], tip});
  const b0 = Math.floor(Math.min(...err)), b1 = Math.ceil(Math.max(...err)), groups = [];
  for (let b = b0; b < b1; b++) groups.push({label:`${b}`, values:[err.filter(e => e >= b && e < b+1).length]});
  bars($("#chHist"), {xlabel:"error band (%), from the value shown up to +1", ylabel:"rows", series:[{name:"rows", color:MCOL[m.key]}], groups});

  $("#minErr").oninput = e => { MINERR = Math.abs(Number(e.target.value)) || 0; drawRows(); };
  $("#dl").onclick = downloadCsv;
  drawRows();
}

const COLS = [["row","Row"],["V","Voltage (V)"],["R","Resistance (Ω)"],["I_uA","I (µA)"],["P_kPa","P (kPa)"],["T_K","T (K)"],["C","Known %"],["pred","Predicted %"],["err","Error %"]];
function drawRows(){
  const d = RES.data, m = M;
  let rows = d.C.map((c,i) => ({row:d.row[i], V:d.V[i], R:d.R[i], I_uA:d.I_uA[i], P_kPa:d.P_kPa[i], T_K:d.T_K[i], C:c, pred:m.pred[i], err:m.pred[i]-c}));
  const total = rows.length;
  if (MINERR > 0) rows = rows.filter(r => Math.abs(r.err) >= MINERR);
  rows.sort((a,b) => (a[SORT.col] - b[SORT.col]) * SORT.dir);
  $("#rowInfo").textContent = MINERR > 0 ? `${rows.length} of ${total} rows have |error| ≥ ${MINERR} %.` : `${total} rows. Row = row number in the uploaded file (after the header).`;
  const cls = e => Math.abs(e) <= 1 ? "good" : Math.abs(e) > 3 ? "bad" : "";
  $("#rows").innerHTML = `<thead><tr>${COLS.map(([k,t]) => `<th class="${k==="row"?"l":""}" data-k="${k}" style="cursor:pointer">${t}${SORT.col===k?(SORT.dir>0?" ↑":" ↓"):""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr><td class="l">${r.row}</td><td>${fmt(r.V,6)}</td><td>${fmt(r.R,6)}</td><td>${fx(r.I_uA,4)}</td><td>${fmt(r.P_kPa,5)}</td>
      <td>${fx(r.T_K,2)}</td><td>${fmt(r.C,4)}</td><td>${fx(r.pred,3)}</td><td class="${cls(r.err)}">${r.err>=0?"+":""}${fx(r.err,3)}</td></tr>`).join("")}</tbody>`;
  document.querySelectorAll("#rows th").forEach(th => th.onclick = () => {
    SORT = {col:th.dataset.k, dir: SORT.col === th.dataset.k ? -SORT.dir : 1}; drawRows(); });
}
function downloadCsv(){
  const d = RES.data, m = M;
  const lines = ["row,voltage_V,resistance_ohm,I_uA,P_kPa,T_K,C_known,C_predicted,error"].concat(
    d.C.map((c,i) => [d.row[i], d.V[i], d.R[i], d.I_uA[i], d.P_kPa[i], d.T_K[i], c, m.pred[i], m.pred[i]-c].join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")], {type:"text/csv"}));
  a.download = `${RES.filename.replace(/\.[^.]+$/, "")}_${m.key}.csv`; a.click();
}
