(() => {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  let credential = "";
  let selectedConcurrency = 1;
  let runs = [];
  const fmt = value => value == null ? "—" : Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
  const date = ts => ts ? new Date(ts*1000).toLocaleString() : "—";
  const escape = value => String(value ?? "").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const message = (value) => { const el=$("#toast"); el.textContent=value; el.classList.add("visible"); setTimeout(()=>el.classList.remove("visible"),3200); };
  async function api(path, options={}) {
    const response = await fetch(path, {
      ...options,
      headers: {"Authorization":"Bearer "+credential,...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})},
      cache:"no-store"
    });
    if (response.status===401) { lock(); throw new Error("Operator credential rejected"); }
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(body.detail || "Console request failed");
    return body;
  }
  function lock() { credential=""; $("#operatorToken").value=""; $("#authOverlay").classList.remove("hidden"); }
  function navigate(name) {
    $$(".page").forEach(el=>el.classList.toggle("active",el.id==="page-"+name));
    $$(".nav-item").forEach(el=>el.classList.toggle("active",el.dataset.page===name));
    $("#breadcrumb").textContent=name.replace("-"," ").toUpperCase();
    if (name==="overview") refreshOverview();
    if (name==="history") refreshHistory();
    if (name==="reliability") refreshReliability();
  }
  const good = run => run?.report && run.report.successes===run.report.samples.length;
  const status = run => run?.state==="interrupted"?"INTERRUPTED":good(run)?"PASSED":run?.state==="running"?"RUNNING":"PARTIAL";
  function reportRows(data, detail=false) {
    const list = detail ? data : data.slice(0,5);
    return list.length ? list.map(run=>{
      const r=run.report||{};
      return '<tr><td>'+escape(run.id.slice(0,9))+'</td><td>'+escape(run.profile)+'</td>'+
        '<td>'+run.requested+' / '+run.concurrency+'×</td>'+
        (detail?'<td>'+fmt(r.successes||0)+' / '+run.requested+'</td>':'')+
        '<td>'+ (r.p95_ms==null?'—':fmt(r.p95_ms)+' ms') +'</td>'+
        '<td><span class="status-label '+(good(run)?"":"bad")+'">'+status(run)+'</span></td>'+
        (detail?'<td><button class="table-action" data-run="'+escape(run.id)+'">Inspect →</button></td>':'<td>'+date(run.started_at)+'</td>')+
        '</tr>';
    }).join(""):'<tr><td colspan="'+(detail?7:6)+'" class="empty-row">No benchmarks recorded yet.</td></tr>';
  }
  function plotTrend(all) {
    const series=all.filter(x=>x.report?.p95_ms!=null).slice(0,12).reverse();
    if (!series.length) { $("#trendPlot").innerHTML='<div class="empty-state">Complete a benchmark to populate the trend.</div>'; return; }
    const max=Math.max(1,...series.map(x=>x.report.p95_ms))*1.12;
    const W=640,H=210,p=38;
    const points=series.map((item,index)=>({x:p+(W-2*p)*(series.length===1?.5:index/(series.length-1)),y:H-p-(H-2*p)*(item.report.p95_ms/max),v:item.report.p95_ms}));
    const poly=points.map(x=>x.x+','+x.y).join(' ');
    const area=p+','+(H-p)+' '+poly+' '+points.at(-1).x+','+(H-p);
    let svg='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="P95 trend in milliseconds">';
    [0,.25,.5,.75,1].forEach(t=>{const y=p+(H-2*p)*t;svg+='<line x1="'+p+'" y1="'+y+'" x2="'+(W-p)+'" y2="'+y+'" stroke="#2a3d47" stroke-dasharray="4 5"/><text x="2" y="'+(y+3)+'">'+Math.round(max*(1-t))+'</text>';});
    svg+='<polygon points="'+area+'" fill="#92e7bd" opacity=".08"/><polyline points="'+poly+'" fill="none" stroke="#9cebc6" stroke-width="3" stroke-linejoin="round"/>';
    points.forEach(q=>svg+='<circle cx="'+q.x+'" cy="'+q.y+'" r="5" fill="#9cebc6"><title>'+fmt(q.v)+' ms</title></circle>');
    svg+='</svg>';
    $("#trendPlot").innerHTML=svg;
  }
  function breakdown(data) {
    const root=$("#breakdown"),note=$("#telemetryNote");
    if (!data.available || !data.series.length) {
      root.innerHTML='<div class="empty-state">Telemetry not available.</div>';
      note.textContent=data.reason || "Waiting for Gateway observations";
      return;
    }
    const labels={request:"HTTP requests",queue_local:"Local queue",queue_global:"Global queue",inference:"Model execution",stream:"Streaming"};
    const max=Math.max(1,...data.series.map(x=>x.avg_ms||0));
    root.innerHTML=data.series.map(item=>'<div class="breakdown-item"><div class="breakdown-title"><span>'+
      labels[item.kind]+'</span><b>'+fmt(item.avg_ms)+' ms</b></div><div class="track"><div class="fill" style="width:'+
      Math.max(2,(item.avg_ms||0)*100/max)+'%"></div></div></div>').join("");
    note.textContent="Process-local averages · All observed requests · "+data.series.reduce((v,x)=>v+x.errors,0)+" non-success events";
  }
  async function refreshOverview() {
    if (!credential) return;
    try {
      const [overview,history,telemetry]=await Promise.all([api("/api/overview"),api("/api/runs"),api("/api/telemetry")]);
      runs=history.runs;
      const online=overview.gateway.status==="healthy";
      $("#gatewayState").textContent=online?"Connected":overview.gateway.status==="unhealthy"?"Degraded":"Unreachable";
      $("#gatewayLatency").textContent=online?fmt(overview.gateway.latency_ms)+" ms / health response":"Check Gateway service";
      $("#modelLabel").textContent=overview.model_label;
      $("#latestP95").textContent=overview.latest_run?.report?.p95_ms!=null?fmt(overview.latest_run.report.p95_ms):"—";
      $("#p95Detail").textContent=overview.latest_run?.id?"RUN "+overview.latest_run.id.slice(0,10):"No benchmark data yet";
      const report=overview.latest_run?.report;
      $("#successRate").textContent=report?.samples?.length?Math.round(report.successes*100/report.samples.length)+"%":"—";
      $("#successDetail").textContent=report?report.successes+"/"+report.samples.length+" successful responses":"Awaiting first test";
      $("#recentTable").innerHTML=reportRows(runs);
      plotTrend(runs);
      breakdown(telemetry);
    } catch(e) { if (credential) message(e.message); }
  }
  function resultHTML(report) {
    const percentage=report.samples.length?Math.round(100*report.successes/report.samples.length):0;
    const max=Math.max(1,...report.samples.map(x=>x.latency_ms));
    return '<h3>Run completed · '+percentage+'% successful</h3><p>'+report.samples.length+' samples recorded. Only successful responses contribute to latency percentiles.</p>'+
      '<div class="result-metrics"><div class="result-box"><small>P50 LATENCY</small><strong>'+fmt(report.p50_ms)+' <small>ms</small></strong></div>'+
      '<div class="result-box"><small>P95 LATENCY</small><strong>'+fmt(report.p95_ms)+' <small>ms</small></strong></div>'+
      '<div class="result-box"><small>THROUGHPUT</small><strong>'+fmt(report.throughput_per_min)+' <small>/min</small></strong></div>'+
      '<div class="result-box"><small>FAILED CALLS</small><strong>'+report.failures+'</strong></div></div>'+
      '<div class="eyebrow">SAMPLE LATENCIES</div><div class="mini-bars">'+report.samples.map(s=>
      '<div class="mini-bar '+(s.ok?'good':'')+'" style="height:'+(s.ok?Math.max(3,s.latency_ms*100/max):3)+'%" data-label="#'+s.number+': '+fmt(s.latency_ms)+'ms ('+escape(s.status)+')"></div>').join("")+'</div>';
  }
  async function refreshHistory() {
    if (!credential) return;
    try {
      runs=(await api("/api/runs")).runs;
      $("#historyCount").textContent=runs.length+" RUNS";
      $("#historyTable").innerHTML=reportRows(runs,true);
      $$("[data-run]").forEach(button=>button.addEventListener("click",()=>selectRun(button.dataset.run)));
    } catch(e) { if(credential) message(e.message); }
  }
  async function selectRun(id) {
    const run=runs.find(x=>x.id===id) || await api("/api/runs/"+encodeURIComponent(id));
    const target=$("#runDetail");
    if (!run.report) {target.innerHTML='<div class="empty-state">This experiment was interrupted before the report was saved.</div>';return;}
    const r=run.report;
    target.innerHTML='<div class="section-head"><div><div class="eyebrow">REPORT / '+escape(run.id.slice(0,12))+'</div><h2>'+escape(run.profile)+' · '+escape(run.model_label)+'</h2></div><span class="subtle-pill">'+status(run)+'</span></div>'+
      '<div class="detail-grid"><div><small>P50 LATENCY</small><strong>'+fmt(r.p50_ms)+' ms</strong></div>'+
      '<div><small>P95 LATENCY</small><strong>'+fmt(r.p95_ms)+' ms</strong></div>'+
      '<div><small>THROUGHPUT</small><strong>'+fmt(r.throughput_per_min)+'/m</strong></div>'+
      '<div><small>SUCCESS</small><strong>'+r.successes+'/'+r.samples.length+'</strong></div></div>'+
      '<div class="table-container"><table><thead><tr><th>SAMPLE</th><th>HTTP STATUS</th><th>LATENCY</th><th>RESULT</th></tr></thead><tbody>'+
      r.samples.map(s=>'<tr><td>#'+s.number+'</td><td>'+escape(s.status)+'</td><td>'+fmt(s.latency_ms)+' ms</td><td><span class="status-label '+(s.ok?"":"bad")+'">'+(s.ok?"SUCCESS":"FAILED")+'</span></td></tr>').join("")+'</tbody></table></div>';
  }
  async function refreshReliability() {
    if (!credential) return;
    try {
      const [overview,metrics]=await Promise.all([api("/api/overview"),api("/api/telemetry")]);
      $("#diagnosticHealth").textContent=overview.gateway.status==="healthy"?"Healthy":"Unreachable";
      $("#diagnosticHealthDetail").textContent=overview.gateway.latency_ms==null?"No successful health response":fmt(overview.gateway.latency_ms)+" ms / latest health probe";
      $("#diagnosticMetrics").textContent=metrics.available?"Connected":"Unavailable";
      $("#diagnosticMetricsDetail").textContent=metrics.available?metrics.series.length+" operation categories reported":metrics.reason;
    } catch(e) { if(credential) message(e.message); }
  }
  $("#authForm").addEventListener("submit",async event=>{
    event.preventDefault();
    credential=$("#operatorToken").value.trim();
    $("#authError").textContent="";
    try {
      await api("/api/runs");
      $("#authOverlay").classList.add("hidden");
      $("#operatorToken").value="";
      navigate("overview");
    } catch(e) { $("#authError").textContent=e.message; }
  });
  $("#lockButton").addEventListener("click",lock);
  $$(".nav-item").forEach(node=>node.addEventListener("click",()=>navigate(node.dataset.page)));
  $$("[data-goto]").forEach(node=>node.addEventListener("click",()=>navigate(node.dataset.goto)));
  $("#refreshOverview").addEventListener("click",refreshOverview);
  $("#refreshHistory").addEventListener("click",refreshHistory);
  $("#refreshDiagnostics").addEventListener("click",refreshReliability);
  $("#samples").addEventListener("input",()=>{const n=Number($("#samples").value);$("#samplesValue").value=n;if(selectedConcurrency>n){selectedConcurrency=n;updateConcurrency();}});
  function updateConcurrency() {$$("[data-count]").forEach(b=>{b.classList.toggle("selected",Number(b.dataset.count)===selectedConcurrency);b.disabled=Number(b.dataset.count)>Number($("#samples").value);});}
  $$("[data-count]").forEach(b=>b.addEventListener("click",()=>{selectedConcurrency=Number(b.dataset.count);updateConcurrency();}));
  $("#benchmarkForm").addEventListener("submit",async event=>{
    event.preventDefault();
    const button=$("#runButton");button.disabled=true;button.textContent="RUNNING BENCHMARK…";
    $("#resultState").textContent="RUNNING";
    $("#resultArea").className="result-area";
    $("#resultArea").innerHTML='<div class="idle-illustration"><span>⌁</span></div><h3>Measuring the Gateway</h3><p>Running actual requests against the configured provider. This may take some time depending on inference latency.</p>';
    try {
      const result=await api("/api/benchmarks",{method:"POST",body:JSON.stringify({
        profile:$("#profile").value,samples:Number($("#samples").value),concurrency:selectedConcurrency
      })});
      $("#resultState").textContent=result.state.toUpperCase();
      $("#resultArea").className="result-area report";
      $("#resultArea").innerHTML=resultHTML(result.report);
      message("Benchmark saved · "+result.id.slice(0,10));
    } catch(e) {
      $("#resultState").textContent="FAILED";
      $("#resultArea").innerHTML='<h3>Benchmark unavailable</h3><p>'+escape(e.message)+'</p>';
    } finally {
      button.disabled=false;button.innerHTML='▶ &nbsp;Start benchmark <span>↗</span>';
    }
  });
  setInterval(()=>{$("#clock").textContent=new Date().toLocaleTimeString([], {hour12:false});},1000);
  $("#clock").textContent=new Date().toLocaleTimeString([], {hour12:false});
  updateConcurrency();
})();