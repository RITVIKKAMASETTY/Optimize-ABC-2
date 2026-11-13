"use strict";
/* ---------------- helpers ---------------- */
const $ = s => document.querySelector(s);
// Concentration is ordinal, so levels get one blue hue from dark (low %) to light (high %),
// plus a repeating marker shape as a second cue. Built from the levels in the data.
let LV_HEX = {}, LV_SHAPE = {};
const LV_STOPS = ["#256abf","#3987e5","#6da7ec","#9ec5f4","#cde2fb"];
function setupLevels(levels){
  LV_HEX = {}; LV_SHAPE = {};
  const shapes = ["circle","square","triangle","diamond"], n = levels.length;
  levels.forEach((c,i) => { const t = n > 1 ? i/(n-1) : 0, s = t*(LV_STOPS.length-1), j = Math.min(Math.floor(s), LV_STOPS.length-2);
    LV_HEX[String(c)] = lerpHex(LV_STOPS[j], LV_STOPS[j+1], s-j); LV_SHAPE[String(c)] = shapes[i % 4]; });
}
const EXCL = "#8a8a8a";
const COL = {phys:"#d95926", corr:"#ededed", theory:"#6e6e6e", kn:"#3987e5", bk:"#199e70"};
let R = null, PRED = null, MODEL = "corr";

function fmt(v, d=3){
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(Math.max(d-1,1));
  return (+v.toFixed(d)).toLocaleString("en-US",{maximumFractionDigits:d, minimumFractionDigits:0});
}
const fx = (v,d=2) => (v===null||!isFinite(v)) ? "—" : Number(v).toFixed(d);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("on"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("on"),2600); }
async function api(url, opts){ const r = await fetch(url, opts); const j = await r.json(); if(!r.ok) throw new Error(j.error||r.statusText); return j; }

/* ---------------- tiny SVG chart library ---------------- */
function niceTicks(min, max, n=5){
  if (min === max){ min -= 1; max += 1; }
  const raw = (max-min)/n, mag = Math.pow(10, Math.floor(Math.log10(raw))), e = raw/mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(min/step - 1e-9)*step; v <= max + step*1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
function logTicks(min, max){
  const out = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++){
    for (const m of [1,2,5]){ const v = m*Math.pow(10,e); if (v >= min*0.999 && v <= max*1.001) out.push(v); }
  }
  return out.length >= 2 ? out : [min, max];
}
function shapePath(shape, x, y, r){
  switch(shape){
    case "square":   return `M${x-r*.88},${y-r*.88}h${r*1.76}v${r*1.76}h${-r*1.76}z`;
    case "triangle": return `M${x},${y-r*1.15}L${x+r*1.05},${y+r*.75}L${x-r*1.05},${y+r*.75}z`;
    case "diamond":  return `M${x},${y-r*1.2}L${x+r*1.2},${y}L${x},${y+r*1.2}L${x-r*1.2},${y}z`;
    default:         return `M${x-r},${y}a${r},${r} 0 1,0 ${2*r},0a${r},${r} 0 1,0 ${-2*r},0`;
  }
}
function legendHTML(items){
  return `<div class="legend">${items.map(s => {
    const sym = s.type === "line"
      ? `<svg viewBox="0 0 18 12"><line x1="1" y1="6" x2="17" y2="6" stroke="${s.color}" stroke-width="2" ${s.dash?`stroke-dasharray="${s.dash}"`:""} stroke-linecap="round"/></svg>`
      : `<svg viewBox="0 0 18 12"><path d="${shapePath(s.shape||"circle",9,6,4)}" ${s.hollow?`fill="none" stroke="${s.color}" stroke-width="1.5"`:`fill="${s.color}"`}/></svg>`;
    return `<span>${sym}${esc(s.name)}</span>`;
  }).join("")}</div>`;
}
const CHARTS = new Map();
function plot(el, o){
  CHARTS.set(el, () => plot(el, o));
  const W = Math.max(el.clientWidth || 600, 260), H = o.height || 280;
  const m = {l:o.y.log ? 64 : 56, r:16, t:10, b:42};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const all = [];
  for (const s of o.series) if (!s.noExtent) for (const p of s.pts) if (Number.isFinite(p[0]) && Number.isFinite(p[1])) all.push(p);
  const ext = (k, ax) => {
    let lo = ax.min ?? Math.min(...all.map(p=>p[k])), hi = ax.max ?? Math.max(...all.map(p=>p[k]));
    if (!ax.log && ax.min === undefined && ax.max === undefined){ const pad=(hi-lo)*0.06||1; lo-=pad; hi+=pad; }
    if (ax.log){ lo = ax.min ?? lo/1.15; hi = ax.max ?? hi*1.15; }
    return [lo, hi];
  };
  const [x0,x1] = ext(0, o.x), [y0,y1] = ext(1, o.y);
  const sc = (lo, hi, log, a, b) => log
    ? v => a + (Math.log10(v)-Math.log10(lo))/(Math.log10(hi)-Math.log10(lo))*(b-a)
    : v => a + (v-lo)/(hi-lo)*(b-a);
  const X = sc(x0,x1,o.x.log,m.l,m.l+iw), Y = sc(y0,y1,o.y.log,m.t+ih,m.t);
  const xt = o.x.log ? logTicks(x0,x1) : niceTicks(x0,x1,o.x.ticks||6).filter(v=>v>=x0&&v<=x1);
  const yt = o.y.log ? logTicks(y0,y1) : niceTicks(y0,y1,o.y.ticks||5).filter(v=>v>=y0&&v<=y1);
  const logFmt = v => { const a = Math.abs(v); return (a < 1e-3 || a >= 1e5) ? v.toExponential(0).replace("e-","e−") : fmt(v,3); };
  const tf = o.x.fmt || (o.x.log ? logFmt : v=>fmt(v,3)), tfy = o.y.fmt || (o.y.log ? logFmt : v=>fmt(v,3));
  let g = `<defs><clipPath id="cp${el.id}"><rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/></clipPath></defs>`;
  for (const v of yt) g += `<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/>
    <text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${tfy(v)}</text>`;
  for (const v of xt) g += `<line y1="${m.t}" y2="${m.t+ih}" x1="${X(v)}" x2="${X(v)}" stroke="var(--grid)"/>
    <text x="${X(v)}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${tf(v)}</text>`;
  g += `<line x1="${m.l}" x2="${m.l+iw}" y1="${m.t+ih}" y2="${m.t+ih}" stroke="var(--axis)"/>`;
  g += `<text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.x.label||"")}</text>`;
  g += `<text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.y.label||"")}</text>`;
  let body = "";
  for (const b of (o.bands||[])){
    const ya = Y(Math.min(Math.max(b.y1,y0),y1)), yb = Y(Math.max(Math.min(b.y0,y1),y0));
    body += `<rect x="${m.l}" width="${iw}" y="${ya}" height="${Math.max(yb-ya,0)}" fill="#fff" fill-opacity=".035"/>
      <text x="${m.l+iw-6}" y="${ya+14}" text-anchor="end" fill="var(--muted)" font-size="11">${esc(b.label||"")}</text>`;
  }
  for (const s of o.series.filter(s=>s.type==="line")){
    let d = "", pen = false;
    for (const p of s.pts){
      if (!Number.isFinite(p[0])||!Number.isFinite(p[1])||(o.y.log&&p[1]<=0)){ pen=false; continue; }
      d += (pen?"L":"M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1); pen = true;
    }
    body += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width||2}" stroke-linejoin="round" stroke-linecap="round" ${s.dash?`stroke-dasharray="${s.dash}"`:""} ${s.opacity?`stroke-opacity="${s.opacity}"`:""}/>`;
  }
  for (const s of o.series.filter(s=>s.type!=="line")){
    for (const p of s.pts){
      if (!Number.isFinite(p[0])||!Number.isFinite(p[1])) continue;
      body += s.hollow
        ? `<path d="${shapePath(s.shape||"circle", X(p[0]), Y(p[1]), s.r||4)}" fill="none" stroke="${s.color}" stroke-width="1.5"/>`
        : `<path d="${shapePath(s.shape||"circle", X(p[0]), Y(p[1]), s.r||4)}" fill="${s.color}" stroke="var(--surface)" stroke-width="1.5" ${s.opacity?`fill-opacity="${s.opacity}"`:""}/>`;
    }
  }
  if (o.marker){
    const mx = X(o.marker.x), my = Y(o.marker.y);
    if (isFinite(mx) && isFinite(my)) body += `
      <line x1="${mx}" x2="${mx}" y1="${m.t}" y2="${m.t+ih}" stroke="#fff" stroke-opacity=".35" stroke-dasharray="3 3"/>
      <line x1="${m.l}" x2="${m.l+iw}" y1="${my}" y2="${my}" stroke="#fff" stroke-opacity=".35" stroke-dasharray="3 3"/>
      <circle cx="${mx}" cy="${my}" r="7" fill="none" stroke="#fff" stroke-width="2"/>
      <circle cx="${mx}" cy="${my}" r="2.5" fill="#fff"/>
      <text x="${Math.min(mx+11, m.l+iw-4)}" y="${Math.max(my-10, m.t+12)}" text-anchor="${mx > m.l+iw-120 ? "end":"start"}" fill="#fff" font-size="12" font-weight="600">${esc(o.marker.label||"")}</text>`;
  }
  const leg = o.legend === false ? "" : legendHTML(o.series.filter(s=>s.name && !s.hideLegend));
  el.innerHTML = `${leg}<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.aria||o.y.label||"chart")}">
    ${g}<g clip-path="url(#cp${el.id})">${body}</g><g class="hl"></g>
    <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/></svg><div class="tip"></div></div>`;
  // hover layer: nearest point (pixel distance)
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), hl = el.querySelector(".hl");
  const pts = [];
  for (const s of o.series){ if (s.noHover) continue;
    for (const p of s.pts) if (Number.isFinite(p[0])&&Number.isFinite(p[1])) pts.push({px:X(p[0]),py:Y(p[1]),p,s}); }
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W / r.width;
    const mx = (ev.clientX - r.left)*k, my = (ev.clientY - r.top)*k;
    let best = null, bd = 1e9;
    for (const q of pts){ const d = (q.px-mx)**2 + (q.py-my)**2; if (d < bd){ bd = d; best = q; } }
    if (!best || bd > 40*40){ tip.style.opacity = 0; hl.innerHTML = ""; return; }
    hl.innerHTML = `<circle cx="${best.px}" cy="${best.py}" r="6.5" fill="none" stroke="#fff" stroke-width="1.5"/>`;
    const lines = o.tip ? o.tip(best.p, best.s) : [`${o.x.label}: ${fmt(best.p[0],4)}`, `${o.y.label}: ${fmt(best.p[1],4)}`];
    tip.innerHTML = `<div class="n">${esc(best.s.name||"")}</div>` + lines.map(esc).join("<br>");
    tip.style.opacity = 1;
    const tx = best.px / k, ty = best.py / k + (leg ? el.querySelector(".legend").offsetHeight + 8 : 0);
    tip.style.left = Math.min(tx + 14, r.width - tip.offsetWidth - 4) + "px";
    tip.style.top = Math.max(ty - tip.offsetHeight - 10, 0) + "px";
    tip.parentElement.style.position = "relative";
  });
  svg.addEventListener("mouseleave", () => { tip.style.opacity = 0; hl.innerHTML = ""; });
}

/* heatmap for the loss landscape (log axes on A and B) */
function lerpHex(a, b, t){ const p = h => [1,3,5].map(i => parseInt(h.slice(i,i+2),16)); const A=p(a),B=p(b);
  return "#" + A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,"0")).join(""); }
const RAMP = ["#0b1a33","#104281","#1c5cab","#3987e5","#86b6ef","#cde2fb"]; // high loss (dark) -> low loss (bright)
function rampColor(t){ t = Math.min(Math.max(t,0),1); const s = t*(RAMP.length-1), i = Math.min(Math.floor(s), RAMP.length-2); return lerpHex(RAMP[i], RAMP[i+1], s-i); }
function heatmap(el, o){
  CHARTS.set(el, () => heatmap(el, o));
  const W = Math.max(el.clientWidth || 600, 260), H = o.height || 320, m = {l:60,r:16,t:10,b:42};
  const iw = W-m.l-m.r, ih = H-m.t-m.b, xs = o.xv, ys = o.yv, Z = o.z;
  const lx0 = Math.log10(xs[0]), lx1 = Math.log10(xs[xs.length-1]), ly0 = Math.log10(ys[0]), ly1 = Math.log10(ys[ys.length-1]);
  const X = v => m.l + (Math.log10(v)-lx0)/(lx1-lx0)*iw, Y = v => m.t + ih - (Math.log10(v)-ly0)/(ly1-ly0)*ih;
  let zmin = Infinity, zmax = -Infinity; for (const r of Z) for (const v of r){ zmin=Math.min(zmin,v); zmax=Math.max(zmax,v); }
  const cw = iw/xs.length, ch = ih/ys.length;
  let cells = "";
  for (let i=0;i<xs.length;i++) for (let j=0;j<ys.length;j++){
    const t = 1 - (Z[i][j]-zmin)/(zmax-zmin);
    cells += `<rect x="${(m.l+i*cw).toFixed(1)}" y="${(m.t+ih-(j+1)*ch).toFixed(1)}" width="${(cw+0.6).toFixed(1)}" height="${(ch+0.6).toFixed(1)}" fill="${rampColor(t*t)}"/>`;
  }
  let axes = "";
  for (const v of logTicks(xs[0], xs[xs.length-1])) axes += `<line x1="${X(v)}" x2="${X(v)}" y1="${m.t+ih}" y2="${m.t+ih+4}" stroke="var(--axis)"/><text x="${X(v)}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,3)}</text>`;
  for (const v of logTicks(ys[0], ys[ys.length-1])) axes += `<line x1="${m.l-4}" x2="${m.l}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--axis)"/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,3)}</text>`;
  axes += `<text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.xlabel)}</text>
    <text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.ylabel)}</text>`;
  const path = o.path.map((p,i)=>(i?"L":"M")+X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)).join("");
  let marks = `<path d="${path}" fill="none" stroke="${COL.phys}" stroke-width="2" stroke-linejoin="round"/>`;
  o.path.forEach((p,i)=> marks += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${i?3.5:4.5}" fill="${COL.phys}" stroke="#000" stroke-width="1.5"/>`);
  for (const p of o.points){
    const px = X(p.x), py = Y(p.y);
    marks += `<path d="${shapePath(p.shape||"circle",px,py,p.r||5)}" fill="${p.fill||"#fff"}" stroke="#000" stroke-width="2"/>
      <text x="${px + (p.dx??10)}" y="${py + (p.dy??-8)}" text-anchor="${p.anchor||"start"}" fill="#fff" font-size="12" font-weight="600" paint-order="stroke" stroke="#000" stroke-width="3">${esc(p.label)}</text>`;
  }
  const gradStops = RAMP.map((c,i)=>`<stop offset="${i/(RAMP.length-1)}" stop-color="${c}"/>`).join("");
  el.innerHTML = `<div class="legend"><span><svg viewBox="0 0 18 12"><line x1="1" y1="6" x2="17" y2="6" stroke="${COL.phys}" stroke-width="2"/></svg>Levenberg–Marquardt path</span>
      <span><svg viewBox="0 0 60 12" style="width:60px"><defs><linearGradient id="lg${el.id}">${gradStops}</linearGradient></defs><rect x="0" y="2" width="60" height="8" rx="2" fill="url(#lg${el.id})"/></svg>log₁₀ SSE: high → low (bright = better fit)</span></div>
    <div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Loss landscape over A and B">${cells}${axes}${marks}
    <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg><div class="tip"></div></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W/r.width, mx = (ev.clientX-r.left)*k, my = (ev.clientY-r.top)*k;
    const i = Math.floor((mx-m.l)/cw), j = Math.floor((m.t+ih-my)/ch);
    if (i<0||j<0||i>=xs.length||j>=ys.length){ tip.style.opacity=0; return; }
    tip.innerHTML = `<div class="n">Loss surface</div>A = ${fmt(xs[i],4)}<br>B = ${fmt(ys[j],4)}<br>SSE = ${fmt(Math.pow(10,Z[i][j]),4)}`;
    tip.style.opacity = 1;
    tip.style.left = Math.min(mx/k+14, r.width-tip.offsetWidth-4)+"px";
    tip.style.top = Math.max(my/k + el.querySelector(".legend").offsetHeight - tip.offsetHeight + 0, 0)+"px";
  });
  svg.addEventListener("mouseleave", ()=> tip.style.opacity=0);
}

/* grouped bars (MAE per concentration level per model) */
function bars(el, o){
  CHARTS.set(el, () => bars(el, o));
  const W = Math.max(el.clientWidth||600, 260), H = o.height||280, m = {l:56,r:16,t:10,b:42};
  const iw = W-m.l-m.r, ih = H-m.t-m.b;
  const ymax = Math.max(...o.groups.flatMap(g=>g.values)) * 1.12;
  const yt = niceTicks(0, ymax, 5).filter(v=>v<=ymax);
  const Y = v => m.t + ih - v/ymax*ih;
  const gw = iw/o.groups.length, n = o.series.length, gap = 2, bw = Math.min(28, (gw*0.7 - gap*(n-1))/n);
  let s = "";
  for (const v of yt) s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,2)}</text>`;
  const rects = [];
  o.groups.forEach((g, gi) => {
    const cx = m.l + gw*gi + gw/2, start = cx - (n*bw + (n-1)*gap)/2;
    g.values.forEach((v, si) => {
      const x = start + si*(bw+gap), y = Y(v), h = m.t+ih-y, rr = Math.min(4, h, bw/2);
      s += `<path d="M${x},${m.t+ih}V${y+rr}Q${x},${y} ${x+rr},${y}H${x+bw-rr}Q${x+bw},${y} ${x+bw},${y+rr}V${m.t+ih}Z" fill="${o.series[si].color}"/>`;
      rects.push({x, y, w:bw, h, v, g:g.label, s:o.series[si].name});
    });
    s += `<text x="${cx}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${esc(g.label)}</text>`;
  });
  s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${m.t+ih}" y2="${m.t+ih}" stroke="var(--axis)"/>
    <text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.xlabel)}</text>
    <text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.ylabel)}</text>`;
  el.innerHTML = legendHTML(o.series.map(x=>({...x,type:"bar",shape:"square"}))) + `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.ylabel)}">${s}</svg><div class="tip"></div></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W/r.width, mx=(ev.clientX-r.left)*k, my=(ev.clientY-r.top)*k;
    const b = rects.find(b => mx >= b.x-1 && mx <= b.x+b.w+1 && my >= Math.min(b.y, m.t+ih-12) - 2 && my <= m.t+ih);
    if (!b){ tip.style.opacity=0; return; }
    tip.innerHTML = `<div class="n">${esc(b.s)}</div>${esc(b.g)} O₂ · MAE ${fmt(b.v,3)} %`;
    tip.style.opacity=1; tip.style.left = Math.min(b.x/k+b.w/k+8, r.width-tip.offsetWidth-4)+"px";
    tip.style.top = Math.max(b.y/k + el.querySelector(".legend").offsetHeight - 20, 0)+"px";
  });
  svg.addEventListener("mouseleave", ()=> tip.style.opacity=0);
}

let rsz; window.addEventListener("resize", () => { clearTimeout(rsz); rsz = setTimeout(() => CHARTS.forEach(f => f()), 120); });

/* ---------------- page ---------------- */
function card(id, title, desc, h){ return `<div class="card"><div class="card-h"><h3>${title}</h3></div><p class="desc">${desc}</p><div id="${id}" style="min-height:${h||280}px"></div></div>`; }

function render(){
  const r = R, ph = r.physics, co = r.corrected, th = r.theory, k = co.k, cfg = r.config, ol = r.outliers;
  setupLevels(r.levels);
  const lvTxt = `${r.levels[0]}–${r.levels[r.levels.length-1]} %`;
  const sgn = v => v < 0 ? "− " + fmt(-v,4) : "+ " + fmt(v,4);
  const corrEq = `${fmt(k[0],4)} ${sgn(k[1])}·Cp ${sgn(k[2])}·Cp² ${sgn(k[3])}·Cp³`;
  const exclTxt = Object.entries(ol.by_level).filter(([c,n])=>n>0).map(([c,n])=>`${n} at ${c} %`).join(", ");
  const pct = (a,b) => (100*(1-b/a)).toFixed(0);
  $("#status").innerHTML = `<i></i>Calibrated · RMSE ${fx(co.metrics.RMSE,2)} %`;
  const opts = r.obs.P.map((p,i)=>`<option value="${i}">P ${p} · I ${r.obs.I[i]} µA · actual ${r.obs.C[i]} %${r.obs.used[i]?"":" (excluded)"}</option>`).join("");
  const worst = Object.entries(ph.metrics.per_level).sort((a,b)=>b[1]-a[1])[0];
  $("#app").innerHTML = `
  <section id="predict">
    <p class="eyebrow">Stage 2 · Prediction</p>
    <h1>Oxygen concentration from pressure and current.</h1>
    <p class="lead">Enter a pressure and the measured zirconia sensor current. The calibrated physics model inverts
      <span style="font-family:var(--mono)">I = −(4FSP·Deff / RTL)·ln(1 − C/100)</span> with the optimized A and B, then applies the result correction.</p>
    <div class="grid g-hero">
      <div class="card">
        <div class="field"><label class="f" for="inP">Pressure P</label>
          <div class="inp"><input id="inP" type="number" step="any" min="0" value="56.89" inputmode="decimal"><span class="unit">kPa</span></div></div>
        <div class="field"><label class="f" for="inI">Sensor current I</label>
          <div class="inp"><input id="inI" type="number" step="any" min="0" value="8.082" inputmode="decimal"><span class="unit">µA</span></div></div>
        <div class="field"><label class="f" for="inEx">Or load a calibration reading</label>
          <div class="inp"><select id="inEx"><option value="">Choose a measured point…</option>${opts}</select><span class="unit">▾</span></div></div>
        <div class="row" style="justify-content:space-between;margin-top:6px">
          <div class="seg" id="segModel"><button data-m="corr" class="on">Physics + correction</button><button data-m="phys">Physics only (A, B)</button></div>
          <button class="btn primary" id="btnPredict">Predict</button>
        </div>
      </div>
      <div class="card result">
        <div>
          <div class="card-h"><h3>Predicted O₂ concentration</h3><span class="pill" id="modelPill">physics + correction</span></div>
          <div class="big" id="outC">—</div>
          <div class="note" id="outSub"></div>
          <div id="outWarn"></div>
        </div>
        <dl class="kv" id="outKV"></dl>
      </div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card("chPredCurve","Concentration vs current at this pressure","Every model's C(I) curve at the entered pressure. The ring marks your reading. The shaded band is the calibrated range, and the dotted part of the white curve is extrapolation outside it.")}
      ${card("chMap","Where the reading sits on the calibration map","Measured calibration currents (points) and the calibrated iso-concentration curves (lines). Levels where the correction would extrapolate have no line. Your reading is the ring.")}
    </div>
  </section>

  <section id="calibration">
    <p class="eyebrow">Stage 1 · Calibration</p>
    <h2>Optimized coefficients</h2>
    <p class="lead">${r.data.P.length} pressures × ${r.levels.length} concentrations (${lvTxt}) = ${r.obs.C.length} readings.
      ${ol.enabled ? `The outlier screen left out <b style="color:var(--text)">${ol.n_excluded}</b> readings (${exclTxt || "none"}), so the fit uses ${ol.n_used}. Excluded points are drawn as hollow grey markers.` : "Every reading is used (outlier screen off)."}
      Data: <code>${esc(r.source)}</code></p>
    <div class="tiles">
      <div class="tile"><div class="t">A · Knudsen correction</div><div class="v">${fmt(ph.A,4)}</div><div class="s">± ${fmt(ph.se_A,3)} (1σ)</div></div>
      <div class="tile"><div class="t">B · bulk correction</div><div class="v">${fmt(ph.B,4)}</div><div class="s">± ${fmt(ph.se_B,3)} (1σ)</div></div>
      <div class="tile"><div class="t">Correction k₀ · k₁ · k₂ · k₃</div><div class="v" style="font-size:14px;margin-top:10px;font-family:var(--mono)">${fmt(k[0],3)} · ${fmt(k[1],3)}<br>${fmt(k[2],3)} · ${fmt(k[3],3)}</div><div class="s">cubic in C_phys</div></div>
      <div class="tile"><div class="t">RMSE · theory A=B=1</div><div class="v">${fx(th.metrics.RMSE,2)} %</div><div class="s">R² ${fx(th.metrics.R2,3)}</div></div>
      <div class="tile"><div class="t">RMSE · physics fit</div><div class="v">${fx(ph.metrics.RMSE,2)} %</div><div class="s">R² ${fx(ph.metrics.R2,3)} · −${pct(th.metrics.RMSE,ph.metrics.RMSE)}%</div></div>
      <div class="tile"><div class="t">RMSE · physics + correction</div><div class="v">${fx(co.metrics.RMSE,2)} %</div><div class="s">R² ${fx(co.metrics.R2,3)} · −${pct(th.metrics.RMSE,co.metrics.RMSE)}%</div></div>
    </div>
    <div class="grid g2">
      ${card("chParity","Actual vs predicted","Each column is one known concentration, with the models offset slightly so they don't overlap. On the 45° line, the prediction equals the actual value.")}
      ${card("chLevel","Mean absolute error per concentration",`How each model performs at each concentration (${lvTxt}). Only readings used in the fit.`)}
      ${card("chResPhys","Residuals vs pressure · physics only (A, B)","Predicted − actual. A and B alone cannot match every concentration at once: the low concentrations show a clear bias.")}
      ${card("chResCorr","Residuals vs pressure · physics + correction","The same residuals after the correction, on the same y-scale.")}
      ${card("chCorrMap","Result correction: physics output → concentration","x is the concentration predicted by the A,B physics model and y is the true concentration. The white curve is the fitted map, the dashed line is identity.")}
      ${card("chIP","Sensor current vs pressure · data and model","Points are measured. Solid lines are the calibrated model (physics + correction). Dashed lines are physics only.")}
    </div>
  </section>

  <section id="optimization">
    <p class="eyebrow">Method</p>
    <h2>How A and B are optimized</h2>
    <p class="lead">A and B rescale the Knudsen and bulk diffusion resistances. They are found by minimizing the squared concentration error over the whole dataset.</p>
    <div class="grid g2">
      <div class="card">
        <ol class="steps">
          <li><b>Physics terms per observation.</b> For each (P, I) the code computes Dk = (2a/3)·√(8RT/πM) and Db = D0·(T/273)^α·(P0/P). The inverse model can then be written as
            <div class="eq">C = 100·[1 − exp(−(<span class="hl">A</span>·p + <span class="hl">B</span>·q))]<br>p = I·RTL/(4FSP·Dk) &nbsp; q = I·RTL/(4FSP·Db)</div></li>
          <li><b>Linear starting point.</b> Because −ln(1 − C/100) = A·p + B·q is linear in A and B, ordinary least squares gives a closed-form first estimate:
            A = ${fmt(ph.lin.A,4)}, B = ${fmt(ph.lin.B,4)}.</li>
          <li><b>Levenberg–Marquardt refinement.</b> The real objective is in concentration space:
            <div class="eq">Loss(A,B) = Σᵢ [C_pred(Pᵢ, Iᵢ; A, B) − C_actual,ᵢ]²</div>
            LM is a blend of Gauss–Newton and gradient descent. Each step solves (JᵀJ + λ·diag JᵀJ)·Δ = −Jᵀr. The search runs over log A and log B, so both stay positive. It starts from the theory point (1, 1) and from the linear estimate, and keeps the lower loss.
            It converged in ${ph.history.length-1} iterations: SSE ${fmt(ph.history[0].loss,4)} → ${fmt(ph.history[ph.history.length-1].loss,4)}.</li>
          <li><b>Identifiability check.</b> From the Jacobian at the optimum: corr(A, B) = ${fx(ph.corr_AB,3)}, condition number ${fmt(ph.cond,3)}.
            ${Math.abs(ph.corr_AB) < 0.95 ? "Both coefficients can be identified separately," : "A and B are strongly correlated,"} because the data spans the pressure range where the Knudsen share of resistance moves from
            ${fx(Math.max(...r.diffusion.knudsen_share),0)} % to ${fx(Math.min(...r.diffusion.knudsen_share),0)} % (see the chart below).</li>
          <li><b>Why A and B alone are not enough.</b> At a fixed pressure the physics says I ∝ −ln(1 − C/100). The measured currents follow that law well in the middle of the range, but not at every concentration (the 21 % current is lower than the law predicts). A and B only rescale the curve at each pressure, so they cannot bend its shape. The largest remaining error is at ${worst[0]} % (MAE ${fx(worst[1],2)} %).</li>
          <li><b>Correction applied to the result.</b> With A and B fixed, the physics output is mapped through
            <div class="eq">C = <span class="hl">k₀</span> + <span class="hl">k₁</span>·Cp + <span class="hl">k₂</span>·Cp² + <span class="hl">k₃</span>·Cp³<br>&nbsp; = ${corrEq}</div>
            Cp is the physics result. The k values are found by ordinary least squares, which has an exact one-step solution. The code checks that the curve only goes up across the calibrated band (Cp ${fx(co.lo,1)}–${fx(co.hi,1)} %); if not, it drops to a quadratic, then a straight line. Outside the band it continues as a straight line, so a higher current always means a higher concentration. Degree used: ${co.degree}. RMSE drops from ${fx(ph.metrics.RMSE,2)} % to ${fx(co.metrics.RMSE,2)} %.</li>
          <li><b>Outlier screen.</b> ${ol.enabled ? `The model is fitted, and any reading whose error is more than ${fmt(ol.z,2)} robust standard deviations (1.4826 × median absolute deviation = ${fx(ol.scale,2)} %) from the median is left out. This repeats until nothing changes. ${ol.n_excluded} readings were excluded: ${exclTxt || "none"}. You can switch this off in Parameters.` : "Switched off: every reading is used."}</li>
        </ol>
      </div>
      <div class="grid" style="gap:16px">
        ${card("chLand","Loss landscape over A and B","SSE on a log grid of A and B. Orange is the Levenberg–Marquardt path from the theory point (1, 1). The white point is the optimum and the square is the linear OLS start.",320)}
        ${card("chConv","Convergence","Stage 1 (A, B): sum of squared concentration errors at each accepted iteration. Stage 2 has an exact one-step solution, so it has no iterations.",220)}
      </div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card("chDiff","Diffusion coefficients vs pressure","Dk is independent of pressure. Db falls as 1/P. The effective coefficient follows Bosanquet, both as theory (A=B=1) and as fitted.")}
      ${card("chShare","Share of diffusion resistance","Knudsen term A/Dk vs bulk term B/Db as a fraction of 1/Deff. The share changes across the measured pressures, which is what makes A and B separately identifiable.")}
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div><h3 style="margin:0 0 10px">Stage 1 iterations · A, B</h3><div class="tbl" style="max-height:300px"><table>
        <thead><tr><th>Iter</th><th>A</th><th>B</th><th>SSE</th><th>RMSE %</th><th>λ</th></tr></thead>
        <tbody>${ph.history.map(h=>`<tr><td>${h.it}</td><td>${fmt(h.A,6)}</td><td>${fmt(h.B,6)}</td><td>${fmt(h.loss,5)}</td><td>${fx(Math.sqrt(h.loss/ol.n_used),4)}</td><td>${h.lam.toExponential(1)}</td></tr>`).join("")}</tbody></table></div></div>
      <div><h3 style="margin:0 0 10px">Parameter statistics</h3><div class="tbl"><table style="font-size:12px">
        <thead><tr><th>Parameter</th><th>Estimate</th><th>Std. error</th><th>95 % CI</th></tr></thead>
        <tbody>
          <tr><td class="l">A (Knudsen)</td><td>${fmt(ph.A,5)}</td><td>${fmt(ph.se_A,4)}</td><td>${fmt(ph.ci_A[0],4)} … ${fmt(ph.ci_A[1],4)}</td></tr>
          <tr><td class="l">B (bulk)</td><td>${fmt(ph.B,5)}</td><td>${fmt(ph.se_B,4)}</td><td>${fmt(ph.ci_B[0],4)} … ${fmt(ph.ci_B[1],4)}</td></tr>
          <tr><td class="l">corr(A, B)</td><td>${fx(ph.corr_AB,4)}</td><td class="dim">—</td><td class="dim">${Math.abs(ph.corr_AB)<0.95?"identifiable":"weakly identifiable"}</td></tr>
          <tr><td class="l">k₀ · k₁ · k₂ · k₃</td><td>${k.map(v=>fmt(v,3)).join(" · ")}</td><td class="dim">—</td><td class="dim">deg ${co.degree}</td></tr>
          <tr><td class="l">Dk (constant)</td><td>${fmt(r.Dk,4)}</td><td class="dim">m²/s</td><td class="dim">—</td></tr>
        </tbody></table></div>
        <p class="note">A and B are relative to the geometry in <a href="#parameters">Parameters</a>. If you change a, S or L, A and B rescale to compensate, and the predicted concentrations stay the same. Enter the real sensor specs if you want A and B to have physical meaning.</p></div>
    </div>
  </section>

  <section id="validation">
    <p class="eyebrow">Generalization</p>
    <h2>Validation</h2>
    <p class="lead">Two checks on data the model did not see. (1) Hold-out: every 4th pressure (${r.holdout.test_pressures.map(v=>fmt(v,2)).join(", ")}) is removed, the model is refitted, and it is tested on those rows. (2) Leave-one-pressure-out: ${r.data.P.length} refits, each predicting the pressure it left out. Errors are measured on the ${ol.n_used} readings used in the fit.</p>
    <div class="tbl" style="max-height:none"><table>
      <thead><tr><th>Model</th><th>Fit on all · RMSE</th><th>Fit on all · MAE</th><th>Fit on all · R²</th><th>Hold-out train RMSE</th><th>Hold-out test RMSE</th><th>LOPO-CV RMSE</th><th>LOPO-CV MAE</th><th>Max |error|</th></tr></thead>
      <tbody>
        <tr><td class="l"><span class="sw" style="background:${COL.theory}"></span>Theory (A = B = 1)</td><td>${fx(th.metrics.RMSE,3)}</td><td>${fx(th.metrics.MAE,3)}</td><td>${fx(th.metrics.R2,4)}</td><td class="dim">—</td><td class="dim">—</td><td class="dim">—</td><td class="dim">—</td><td>${fx(th.metrics.MaxAE,2)}</td></tr>
        <tr><td class="l"><span class="sw" style="background:${COL.phys}"></span>Physics fit (A, B)</td><td>${fx(ph.metrics.RMSE,3)}</td><td>${fx(ph.metrics.MAE,3)}</td><td>${fx(ph.metrics.R2,4)}</td><td>${fx(r.holdout.physics.train.RMSE,3)}</td><td>${fx(r.holdout.physics.test.RMSE,3)}</td><td>${fx(r.lopo.physics.RMSE,3)}</td><td>${fx(r.lopo.physics.MAE,3)}</td><td>${fx(ph.metrics.MaxAE,2)}</td></tr>
        <tr><td class="l"><span class="sw" style="background:${COL.corr}"></span>Physics + correction</td><td>${fx(co.metrics.RMSE,3)}</td><td>${fx(co.metrics.MAE,3)}</td><td>${fx(co.metrics.R2,4)}</td><td>${fx(r.holdout.corrected.train.RMSE,3)}</td><td>${fx(r.holdout.corrected.test.RMSE,3)}</td><td>${fx(r.lopo.corrected.RMSE,3)}</td><td>${fx(r.lopo.corrected.MAE,3)}</td><td>${fx(co.metrics.MaxAE,2)}</td></tr>
      </tbody></table></div>
    <p class="note" style="margin-top:12px">All values are in % O₂. The cross-validated error is close to the fitted error, so the model is not overfitting. An exact 0 error is not possible with this data, because some readings go against the trend (sudden steps or dips within a column). The spreadsheet notes flag several handwritten values as uncertain, so check them against the original notebook. Use the model inside the calibrated range: P ${r.ranges.P[0]}–${r.ranges.P[1]} and C ${r.ranges.C[0]}–${r.ranges.C[1]} %.</p>
  </section>

  <section id="parameters">
    <p class="eyebrow">Configuration</p>
    <h2>Sensor &amp; operating parameters</h2>
    <p class="lead">Change these to match your sensor and click Recalibrate. A, B and the correction are refitted on the same experimental data.</p>
    <div class="card">
      <div class="params" id="params"></div>
      <div class="row" style="margin-top:8px"><button class="btn primary" id="btnCal">Recalibrate</button><button class="btn" id="btnReset">Reset defaults</button><span class="note" id="calMsg"></span></div>
    </div>
  </section>

  <section id="data">
    <p class="eyebrow">Table view</p>
    <h2>Experimental data &amp; predictions</h2>
    <p class="lead">Every reading with its prediction from the physics-only model and from physics + correction. Error is the corrected prediction minus the actual value.</p>
    <div class="tbl"><table>
      <thead><tr><th>Pressure</th><th>Actual O₂ %</th><th>Current µA</th><th>Theory %</th><th>C_phys %</th><th>C_final %</th><th>Error %</th><th>Status</th></tr></thead>
      <tbody>${r.obs.P.map((p,i)=>{const e=r.obs.C_corr[i]-r.obs.C[i], u=r.obs.used[i];
        return `<tr${u?"":' style="opacity:.55"'}><td>${p}${r.obs.test[i]?' <span class="dim">·test</span>':""}</td><td>${r.obs.C[i]}</td><td>${r.obs.I[i]}</td><td class="dim">${fx(r.obs.C_theory[i],2)}</td><td class="dim">${fx(r.obs.C_phys[i],2)}</td><td>${fx(r.obs.C_corr[i],2)}</td><td class="${Math.abs(e)<1?"good":Math.abs(e)>3?"bad":""}">${e>=0?"+":""}${fx(e,2)}</td><td class="l">${u?"used":"excluded"}</td></tr>`}).join("")}</tbody>
    </table></div>
  </section>`;

  // parameters form
  const PDEF = [["T","Temperature T","K"],["a","Pore radius a","m"],["S","Cross-section S","m²"],["L","Thickness L","m"],
    ["M","O₂ molar mass M","kg/mol"],["D0","Reference diffusivity D0","m²/s"],["alpha","Temperature exponent α","—"],
    ["P0","Reference pressure P0","data unit"],["P_to_Pa","Pressure unit → Pa","×"],["I_to_A","Current unit → A","×"],
    ["exclude_outliers","Exclude outliers (1 = yes, 0 = no)","0/1"],["outlier_z","Outlier cut-off","× MAD"]];
  $("#params").innerHTML = PDEF.map(([k,l,u])=>`<div class="field"><label class="f" for="cfg_${k}">${l}</label><div class="inp"><input id="cfg_${k}" data-k="${k}" type="number" step="any" value="${cfg[k]}"><span class="unit">${u}</span></div></div>`).join("");
  $("#btnCal").onclick = () => recalibrate("/api/calibrate", Object.fromEntries([...document.querySelectorAll("#params input")].map(i=>[i.dataset.k, i.value])));
  $("#btnReset").onclick = () => recalibrate("/api/reset", {});

  // predictor wiring
  let tmr;
  const go = () => { clearTimeout(tmr); tmr = setTimeout(doPredict, 140); };
  $("#inP").addEventListener("input", go); $("#inI").addEventListener("input", go);
  $("#btnPredict").onclick = doPredict;
  $("#inEx").onchange = e => { const i = e.target.value; if (i === "") return; $("#inP").value = r.obs.P[i]; $("#inI").value = r.obs.I[i]; doPredict(); };
  document.querySelectorAll("#segModel button").forEach(b => b.onclick = () => {
    MODEL = b.dataset.m; document.querySelectorAll("#segModel button").forEach(x=>x.classList.toggle("on", x===b)); showPrediction(); });

  drawCalibrationCharts();
  doPredict();
}

function drawCalibrationCharts(){
  const r = R, o = r.obs, L = r.levels.map(String);
  const byLevel = (fn, extra={}) => {
    const s = L.map(c => ({name:`${c} %`, color:LV_HEX[c], shape:LV_SHAPE[c], type:"scatter", r:3.5,
      pts:o.P.map((p,i)=>i).filter(i=>String(o.C[i])===c && o.used[i]).map(fn), ...extra}));
    const ex = o.P.map((p,i)=>i).filter(i=>!o.used[i]);
    if (ex.length) s.push({name:"excluded", color:EXCL, shape:"circle", hollow:true, type:"scatter", r:4, pts:ex.map(i=>[...fn(i).slice(0,2), ...fn(i).slice(2), `${o.C[i]} % (excluded)`])});
    return s;
  };

  // parity (models dodged horizontally)
  const dodge = {theory:-0.9, phys:0, corr:0.9};
  const ser = (key, name, arr, color) => ({name, color, type:"scatter", r:3, opacity:.9, pts:o.C.map((c,i)=>[c+dodge[key], arr[i], c, o.P[i], o.I[i]]).filter((q,i)=>o.used[i])});
  plot($("#chParity"), {x:{label:"Actual O₂ (%)", min:r.ranges.C[0]-4, max:r.ranges.C[1]+4}, y:{label:"Predicted O₂ (%)"},
    series:[{name:"45° reference", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[0,0],[100,100]]},
      ser("theory","Theory A=B=1",o.C_theory,COL.theory), ser("phys","Physics (A, B)",o.C_phys,COL.phys), ser("corr","Physics + correction",o.C_corr,COL.corr)],
    tip:(p,s)=>[`actual ${p[2]} % · predicted ${fx(p[1],2)} %`, `error ${fx(p[1]-p[2],2)} %`, `P ${p[3]} · I ${p[4]} µA`]});

  bars($("#chLevel"), {xlabel:"Actual O₂ concentration (%)", ylabel:"MAE (% O₂)",
    series:[{name:"Theory A=B=1",color:COL.theory},{name:"Physics (A, B)",color:COL.phys},{name:"Physics + correction",color:COL.corr}],
    groups:L.filter(c=>r.corrected.metrics.per_level[c] !== undefined).map(c=>({label:c, values:[r.theory.metrics.per_level[c], r.physics.metrics.per_level[c], r.corrected.metrics.per_level[c]]}))});

  const allRes = o.C.flatMap((c,i)=> o.used[i] ? [o.C_phys[i]-c, o.C_corr[i]-c] : []);
  const ylim = Math.ceil(Math.max(...allRes.map(Math.abs))) + 0.5;
  const resTip = (p)=>[`P ${p[0]} · residual ${fx(p[1],3)} %`, `I ${p[2]} µA`];
  const zero = {name:"", type:"line", color:"#555", width:1, noHover:true, noExtent:true, hideLegend:true, pts:[[0,0],[1e4,0]]};
  plot($("#chResPhys"), {x:{label:"Pressure"}, y:{label:"Predicted − actual (% O₂)", min:-ylim, max:ylim}, tip:resTip,
    series:[zero, ...byLevel(i=>[o.P[i], o.C_phys[i]-o.C[i], o.I[i]])]});
  plot($("#chResCorr"), {x:{label:"Pressure"}, y:{label:"Predicted − actual (% O₂)", min:-ylim, max:ylim}, tip:resTip,
    series:[zero, ...byLevel(i=>[o.P[i], o.C_corr[i]-o.C[i], o.I[i]])]});

  plot($("#chCorrMap"), {x:{label:"Physics output C_phys (%)"}, y:{label:"Actual / corrected O₂ (%)"},
    series:[{name:"identity", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[0,0],[100,100]]},
      {name:"fitted cubic map", type:"line", color:COL.corr, pts:r.corrected.curve.x.map((x,i)=>[x, r.corrected.curve.y[i]]).filter(p=>p[0]>=r.ranges.C_phys[0]-4 && p[0]<=r.ranges.C_phys[1]+4)},
      ...byLevel(i=>[o.C_phys[i], o.C[i], o.P[i], o.C_corr[i]])],
    tip:(p,s)=> p.length>2 ? [`C_phys ${fx(p[0],2)} % → corrected ${fx(p[3],2)} %`, `actual ${p[1]} % · P ${p[2]}`] : [`C_phys ${fx(p[0],2)} → ${fx(p[1],2)} %`]});

  const cv = r.curves;
  plot($("#chIP"), {x:{label:"Pressure"}, y:{label:"Sensor current (µA)"},
    series:[...L.map(c=>({name:`${c} % physics only`, type:"line", color:LV_HEX[c], dash:"3 4", width:1.5, opacity:.7, hideLegend:true, pts:cv.P.map((p,i)=>[p, cv.physics[c][i]])})),
      ...L.map(c=>({name:`${c} % model`, type:"line", color:LV_HEX[c], hideLegend:true, pts:cv.P.map((p,i)=>[p, cv.corrected[c][i]])})),
      ...byLevel(i=>[o.P[i], o.I[i], o.C[i]])],
    tip:(p,s)=>[`P ${fmt(p[0],4)} · I ${fx(p[1],3)} µA`]});

  // landscape
  const ph = r.physics, Ls = r.landscape;
  heatmap($("#chLand"), {xv:Ls.A, yv:Ls.B, z:Ls.logloss, xlabel:"A (Knudsen coefficient, log)", ylabel:"B (bulk coefficient, log)", height:320,
    path: ph.history.map(h=>[h.A,h.B]),
    points:[{x:1,y:1,label:"theory (1, 1)",fill:COL.theory, shape:"diamond"},
      {x:ph.lin.A,y:ph.lin.B,label:"OLS start",fill:"#86b6ef",shape:"square",dy:18},
      {x:ph.A,y:ph.B,label:`A*=${fmt(ph.A,3)}, B*=${fmt(ph.B,3)}`,fill:"#fff",r:5.5, anchor:"end", dx:-10}]});

  const allLoss = ph.history.map(h=>h.loss);
  plot($("#chConv"), {height:220, x:{label:"Iteration", min:0, max:Math.max(ph.history.length-1, 1), fmt:v=>fmt(v,0)}, y:{label:"SSE (%²)", log:true, min:Math.min(...allLoss, R.corrected.metrics.SSE)/1.5, max:Math.max(...allLoss)*1.5},
    series:[{name:"Stage 1 · A, B", type:"line", color:COL.phys, pts:ph.history.map(h=>[h.it,h.loss])},
      {name:"", type:"scatter", color:COL.phys, r:3.5, hideLegend:true, pts:ph.history.map(h=>[h.it,h.loss])},
      {name:"", type:"line", color:COL.corr, dash:"4 4", width:1.5, noHover:true, hideLegend:true, pts:[[0, R.corrected.metrics.SSE],[Math.max(ph.history.length-1,1), R.corrected.metrics.SSE]]},
      {name:"Stage 2 result (one step)", type:"scatter", color:COL.corr, r:3.5, pts:[[Math.max(ph.history.length-1,1), R.corrected.metrics.SSE]]}],
    tip:(p,s)=>[`iteration ${p[0]}`, `SSE ${fmt(p[1],5)}`, `RMSE ${fx(Math.sqrt(p[1]/R.outliers.n_used),3)} %`]});

  const d = r.diffusion;
  plot($("#chDiff"), {x:{label:"Pressure"}, y:{label:"Diffusion coefficient (m²/s)", log:true},
    series:[{name:"Dk Knudsen", type:"line", color:COL.kn, pts:d.P.map((p,i)=>[p,d.Dk[i]])},
      {name:"Db bulk", type:"line", color:COL.bk, pts:d.P.map((p,i)=>[p,d.Db[i]])},
      {name:"Deff theory (A=B=1)", type:"line", color:COL.theory, dash:"5 4", pts:d.P.map((p,i)=>[p,d.Deff_theory[i]])},
      {name:"Deff fitted (A*, B*)", type:"line", color:COL.corr, pts:d.P.map((p,i)=>[p,d.Deff[i]])}],
    tip:(p,s)=>[`P ${fmt(p[0],4)}`, `${fmt(p[1],4)} m²/s`]});
  plot($("#chShare"), {x:{label:"Pressure"}, y:{label:"Share of 1/Deff (%)", min:0, max:100},
    series:[{name:"Knudsen A/Dk", type:"line", color:COL.kn, pts:d.P.map((p,i)=>[p,d.knudsen_share[i]])},
      {name:"Bulk B/Db", type:"line", color:COL.bk, pts:d.P.map((p,i)=>[p,100-d.knudsen_share[i]])}],
    tip:(p,s)=>[`P ${fmt(p[0],4)}`, `${s.name}: ${fx(p[1],1)} %`]});
}

async function doPredict(){
  const P = parseFloat($("#inP").value), I = parseFloat($("#inI").value);
  if (!(P > 0) || !(I >= 0)){ $("#outC").innerHTML = "—"; $("#outSub").textContent = "Enter a pressure > 0 and a current ≥ 0."; return; }
  try { PRED = await api(`/api/predict?P=${encodeURIComponent(P)}&I=${encodeURIComponent(I)}`); showPrediction(); }
  catch(e){ $("#outSub").textContent = e.message; }
}

function showPrediction(){
  const p = PRED, r = R; if (!p) return;
  const C = MODEL === "corr" ? p.C_corr : p.C_phys;
  $("#outC").innerHTML = `${fx(C,2)}<small>% O₂</small>`;
  $("#modelPill").textContent = MODEL === "corr" ? "physics + correction" : "physics only · A, B";
  const ex = r.obs.P.findIndex((pp,i)=> Math.abs(pp-p.P)<1e-9 && Math.abs(r.obs.I[i]-p.I)<1e-9);
  $("#outSub").innerHTML = ex >= 0
    ? `Calibration reading, known value <b style="color:var(--text)">${r.obs.C[ex]} %</b> · error ${C-r.obs.C[ex]>=0?"+":""}${fx(C-r.obs.C[ex],2)} %`
    : `From P = ${fmt(p.P,4)} and I = ${fmt(p.I,4)} µA`;
  $("#outWarn").innerHTML = p.warnings.map(w=>`<div class="warn"><b>⚠</b><span>${esc(w)}</span></div>`).join("");
  $("#outKV").innerHTML = [
    ["Physics + correction", fx(p.C_corr,3)+" %"], ["Physics only (A, B)", fx(p.C_phys,3)+" %"], ["Theory (A=B=1)", fx(p.C_theory,3)+" %"],
    ["Dk", fmt(p.Dk,4)+" m²/s"], ["Db(T,P)", fmt(p.Db,4)+" m²/s"], ["Deff", fmt(p.Deff,4)+" m²/s"],
    ["Knudsen share", fx(p.knudsen_share,1)+" %"], ["Exponent u", fmt(p.u,4)], ["A · B", `${fmt(r.physics.A,4)} · ${fmt(r.physics.B,4)}`]
  ].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");

  const cv = p.curve, inBand = c => c >= r.ranges.C_phys[0]-1 && c <= r.ranges.C_phys[1]+1;
  plot($("#chPredCurve"), {x:{label:"Sensor current I (µA)", min:0, max:cv.I[cv.I.length-1]}, y:{label:"O₂ concentration (%)", min:0, max:100},
    bands:[{y0:r.ranges.C[0], y1:r.ranges.C[1], label:"calibrated range"}],
    series:[{name:"Theory A=B=1", type:"line", color:COL.theory, dash:"5 4", pts:cv.I.map((x,i)=>[x,cv.theory[i]])},
      {name:"Physics (A, B)", type:"line", color:COL.phys, pts:cv.I.map((x,i)=>[x,cv.phys[i]])},
      {name:"Physics + correction", type:"line", color:COL.corr, pts:cv.I.map((x,i)=>inBand(cv.phys[i]) ? [x,cv.corr[i]] : [x,NaN])},
      {name:"Correction, extrapolated", type:"line", color:COL.corr, dash:"2 4", width:1.5, opacity:.6, pts:cv.I.map((x,i)=>inBand(cv.phys[i]) ? [x,NaN] : [x,cv.corr[i]])}],
    marker:{x:p.I, y:C, label:`${fx(C,2)} %`},
    tip:(q,s)=>[`I ${fx(q[0],3)} µA → ${fx(q[1],2)} %`]});

  const o = r.obs, L = r.levels.map(String), cvv = r.curves;
  plot($("#chMap"), {x:{label:"Pressure"}, y:{label:"Sensor current (µA)"},
    series:[...L.map(c=>({name:`${c} %`, type:"line", color:LV_HEX[c], hideLegend:true, pts:cvv.P.map((pp,i)=>[pp, cvv.corrected[c][i]])})),
      ...L.map(c=>({name:`${c} %`, color:LV_HEX[c], shape:LV_SHAPE[c], type:"scatter", r:3,
        pts:o.P.map((pp,i)=>[pp,o.I[i],o.C[i],o.used[i]]).filter(q=>String(q[2])===c && q[3])})),
      {name:"excluded", color:EXCL, shape:"circle", hollow:true, type:"scatter", r:3.5, pts:o.P.map((pp,i)=>[pp,o.I[i],o.C[i],o.used[i]]).filter(q=>!q[3])}],
    marker:{x:p.P, y:p.I, label:`your reading · ${fx(C,1)} %`},
    tip:(q,s)=>[`P ${fmt(q[0],4)} · I ${fx(q[1],3)} µA`]});
}

async function recalibrate(url, body){
  const b1 = $("#btnCal"), b2 = $("#btnReset"); b1.disabled = b2.disabled = true; $("#calMsg").textContent = "Calibrating…";
  try {
    const keepP = $("#inP").value, keepI = $("#inI").value;
    R = await api(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    render(); $("#inP").value = keepP; $("#inI").value = keepI; doPredict();
    toast(`Recalibrated · A=${fmt(R.physics.A,4)}, B=${fmt(R.physics.B,4)}, RMSE ${fx(R.corrected.metrics.RMSE,2)} %`);
    location.hash = "#parameters";
  } catch(e){ $("#calMsg").textContent = e.message; b1.disabled = b2.disabled = false; }
}

api("/api/results").then(j => { R = j; render(); }).catch(e => { $("#app").innerHTML = `<div class="loading">Failed to load: ${esc(e.message)}</div>`; });
