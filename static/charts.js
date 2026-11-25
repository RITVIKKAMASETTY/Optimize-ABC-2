"use strict";
/* Helpers + a tiny SVG chart library (line/scatter plot and grouped bars). No external libraries. */
const $ = s => document.querySelector(s);

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

/* grouped bars (MAE per concentration level per model) */
function bars(el, o){
  CHARTS.set(el, () => bars(el, o));
  const W = Math.max(el.clientWidth||600, 260), H = o.height||280, m = {l:56,r:16,t:10,b:42};
  const iw = W-m.l-m.r, ih = H-m.t-m.b;
  const vals = o.groups.flatMap(g=>g.values);
  const ymax = Math.max(0, ...vals) * 1.12 || 1, ymin = Math.min(0, ...vals) * 1.12;   // negatives allowed
  const yt = niceTicks(ymin, ymax, 5).filter(v=>v>=ymin && v<=ymax);
  const Y = v => m.t + ih - (v-ymin)/(ymax-ymin)*ih, y0 = Y(0);
  const gw = iw/o.groups.length, n = o.series.length, gap = 2, bw = Math.min(28, (gw*0.7 - gap*(n-1))/n);
  let s = "";
  for (const v of yt) s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,2)}</text>`;
  const rects = [];
  o.groups.forEach((g, gi) => {
    const cx = m.l + gw*gi + gw/2, start = cx - (n*bw + (n-1)*gap)/2;
    g.values.forEach((v, si) => {
      const x = start + si*(bw+gap), y = Y(v), top = Math.min(y, y0), h = Math.max(Math.abs(y0-y), 0.5), rr = Math.min(3, h/2, bw/2);
      s += `<rect x="${x}" y="${top}" width="${bw}" height="${h}" rx="${rr}" fill="${o.series[si].color}"/>`;
      rects.push({x, y:top, w:bw, h, v, g:g.label, s:o.series[si].name});
    });
    s += `<text x="${cx}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${esc(g.label)}</text>`;
  });
  s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${y0}" y2="${y0}" stroke="var(--axis)"/>
    <text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.xlabel)}</text>
    <text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.ylabel)}</text>`;
  el.innerHTML = legendHTML(o.series.map(x=>({...x,type:"bar",shape:"square"}))) + `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.ylabel)}">${s}</svg><div class="tip"></div></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W/r.width, mx=(ev.clientX-r.left)*k, my=(ev.clientY-r.top)*k;
    const b = rects.find(b => mx >= b.x-1 && mx <= b.x+b.w+1 && my >= Math.min(b.y, y0-12) - 2 && my <= Math.max(b.y+b.h, y0+12) + 2);
    if (!b){ tip.style.opacity=0; return; }
    tip.innerHTML = `<div class="n">${esc(b.s)}</div>${esc(b.g)} · ${fmt(b.v,3)}`;
    tip.style.opacity=1; tip.style.left = Math.min(b.x/k+b.w/k+8, r.width-tip.offsetWidth-4)+"px";
    tip.style.top = Math.max(b.y/k + el.querySelector(".legend").offsetHeight - 20, 0)+"px";
  });
  svg.addEventListener("mouseleave", ()=> tip.style.opacity=0);
}

let rsz; window.addEventListener("resize", () => { clearTimeout(rsz); rsz = setTimeout(() => CHARTS.forEach(f => f()), 120); });
