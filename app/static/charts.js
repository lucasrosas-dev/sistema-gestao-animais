function prepareCanvas(canvas, minimumWidth, fallbackHeight) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(minimumWidth, canvas.parentElement?.clientWidth || 0);
  const height = canvas.clientHeight || fallbackHeight;
  canvas.style.width = `${width}px`;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return {ctx, width, height};
}

function drawLineChart(canvasId, labels, values, unit) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !values.length) return;
  const {ctx, width, height} = prepareCanvas(canvas, 700, 290);

  const pad = {left: 48, right: 18, top: 20, bottom: 48};
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);

  ctx.font = '12px Arial';
  ctx.strokeStyle = '#dfe5ea';
  ctx.fillStyle = '#607080';
  ctx.lineWidth = 1;

  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (plotH * i / 4);
    const value = max - (range * i / 4);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(value.toFixed(1), 4, y + 4);
  }

  const xAt = i => labels.length === 1 ? pad.left + plotW / 2 : pad.left + (plotW * i / (labels.length - 1));
  const yAt = v => pad.top + plotH - ((v - min) / range * plotH);

  ctx.strokeStyle = '#235b45';
  ctx.lineWidth = 3;
  ctx.beginPath();
  values.forEach((v, i) => { const x=xAt(i), y=yAt(v); i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y); });
  ctx.stroke();

  values.forEach((v, i) => {
    const x=xAt(i), y=yAt(v);
    ctx.fillStyle='#235b45'; ctx.beginPath(); ctx.arc(x,y,4,0,Math.PI*2); ctx.fill();
  });

  const step = Math.max(1, Math.ceil(labels.length / 6));
  ctx.fillStyle='#607080';
  labels.forEach((label, i) => {
    if (i % step !== 0 && i !== labels.length - 1) return;
    const x=xAt(i); ctx.save(); ctx.translate(x, height - 10); ctx.rotate(-0.35); ctx.textAlign='right'; ctx.fillText(label,0,0); ctx.restore();
  });
  ctx.fillText(unit || '', width - pad.right - 30, 14);
}

function colorForDataset(dataset, index) {
  const raw = String(dataset.id ?? dataset.label ?? index);
  let hash = 0;
  for (let i = 0; i < raw.length; i++) hash = ((hash << 5) - hash) + raw.charCodeAt(i);
  const hue = Math.abs(hash * 47) % 360;
  return `hsl(${hue}, 58%, 42%)`;
}

function drawChartMessage(canvas, message) {
  const {ctx, width, height} = prepareCanvas(canvas, 760, 390);
  ctx.fillStyle = '#607080';
  ctx.font = '15px Arial';
  ctx.textAlign = 'center';
  ctx.fillText(message, width / 2, height / 2);
}

function drawMultiLineChart(canvasId, labels, datasets, legendId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const legend = document.getElementById(legendId);
  if (legend) legend.innerHTML = '';

  if (!labels.length) {
    drawChartMessage(canvas, 'O período informado não possui meses disponíveis.');
    return;
  }
  if (!datasets.length) {
    drawChartMessage(canvas, 'Selecione ao menos um animal para exibir o gráfico.');
    return;
  }

  const minWidth = Math.max(760, labels.length * 92);
  const {ctx, width, height} = prepareCanvas(canvas, minWidth, 390);

  const pad = {left: 82, right: 24, top: 66, bottom: 28};
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const allValues = datasets.flatMap(dataset => dataset.values || []);
  const maxValue = Math.max(...allValues, 0);
  const magnitude = maxValue <= 100 ? 20 : maxValue <= 500 ? 100 : maxValue <= 2000 ? 500 : 1000;
  const roundedMax = Math.max(magnitude, Math.ceil(maxValue / magnitude) * magnitude);

  ctx.font = '12px Arial';
  ctx.lineWidth = 1;
  ctx.strokeStyle = '#dfe5ea';
  ctx.fillStyle = '#607080';

  const currency = value => new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 0
  }).format(value);

  for (let i = 0; i <= 5; i++) {
    const y = pad.top + plotH * i / 5;
    const value = roundedMax - roundedMax * i / 5;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.fillStyle = '#607080';
    ctx.fillText(currency(value), pad.left - 10, y + 4);
  }

  const xAt = index => labels.length === 1
    ? pad.left + plotW / 2
    : pad.left + plotW * index / (labels.length - 1);
  const yAt = value => pad.top + plotH - value / roundedMax * plotH;

  labels.forEach((label, index) => {
    const x = xAt(index);
    ctx.strokeStyle = '#eef1f3';
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + plotH);
    ctx.stroke();
    ctx.fillStyle = '#52606d';
    ctx.textAlign = 'center';
    ctx.fillText(label, x, 30);
  });

  datasets.forEach((dataset, datasetIndex) => {
    const values = dataset.values || [];
    const color = colorForDataset(dataset, datasetIndex);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    values.forEach((value, index) => {
      const x = xAt(index);
      const y = yAt(value);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    values.forEach((value, index) => {
      const x = xAt(index);
      const y = yAt(value);
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  });

  if (legend) {
    datasets.forEach((dataset, index) => {
      const item = document.createElement('span');
      item.className = 'chart-legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'chart-legend-swatch';
      swatch.style.background = colorForDataset(dataset, index);
      const label = document.createElement('span');
      label.textContent = dataset.label;
      item.appendChild(swatch);
      item.appendChild(label);
      legend.appendChild(item);
    });
  }
}

function initMonthlyFinancialChart(config) {
  const selector = document.getElementById(config.selectorId);
  const startInput = document.getElementById(config.startInputId);
  const endInput = document.getElementById(config.endInputId);
  const selectAllButton = document.getElementById(config.selectAllId);
  const clearAnimalsButton = document.getElementById(config.clearAnimalsId);
  const clearPeriodButton = document.getElementById(config.clearPeriodId);
  const summary = document.getElementById(config.summaryId);
  const status = document.getElementById(config.statusId);
  const error = document.getElementById(config.errorId);
  const checkboxes = Array.from(selector?.querySelectorAll('input[type="checkbox"]') || []);
  const datasetById = new Map(config.datasets.map(dataset => [String(dataset.id), dataset]));

  function refresh() {
    const firstMonth = config.monthKeys[0];
    const lastMonth = config.monthKeys[config.monthKeys.length - 1];
    const startValue = startInput?.value || firstMonth;
    const endValue = endInput?.value || lastMonth;

    if (startValue > endValue) {
      if (error) {
        error.hidden = false;
        error.textContent = 'O mês inicial não pode ser posterior ao mês final.';
      }
      drawChartMessage(document.getElementById(config.canvasId), 'Corrija o período informado.');
      document.getElementById(config.legendId).innerHTML = '';
      return;
    }
    if (error) {
      error.hidden = true;
      error.textContent = '';
    }

    const indices = config.monthKeys
      .map((month, index) => ({month, index}))
      .filter(item => item.month >= startValue && item.month <= endValue)
      .map(item => item.index);

    const selectedIds = checkboxes.filter(item => item.checked).map(item => item.value);
    const filteredLabels = indices.map(index => config.monthLabels[index]);
    const filteredDatasets = selectedIds
      .map(id => datasetById.get(id))
      .filter(Boolean)
      .map(dataset => ({
        ...dataset,
        values: indices.map(index => dataset.values[index] ?? 0)
      }));

    drawMultiLineChart(config.canvasId, filteredLabels, filteredDatasets, config.legendId);

    if (summary) {
      summary.textContent = `${selectedIds.length} de ${checkboxes.length} selecionado(s)`;
    }
    if (status) {
      const periodText = filteredLabels.length
        ? `${filteredLabels[0]} a ${filteredLabels[filteredLabels.length - 1]}`
        : 'sem meses no intervalo';
      status.textContent = `${selectedIds.length} animal(is) · ${filteredLabels.length} mês(es) · ${periodText}`;
    }
  }

  checkboxes.forEach(checkbox => checkbox.addEventListener('change', refresh));
  startInput?.addEventListener('change', refresh);
  endInput?.addEventListener('change', refresh);

  selectAllButton?.addEventListener('click', () => {
    checkboxes.forEach(checkbox => { checkbox.checked = true; });
    refresh();
  });

  clearAnimalsButton?.addEventListener('click', () => {
    checkboxes.forEach(checkbox => { checkbox.checked = false; });
    refresh();
  });

  clearPeriodButton?.addEventListener('click', () => {
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    refresh();
  });

  refresh();
  window.addEventListener('resize', refresh);
}

function drawSeriesChart(canvasId, labels, series, legendId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (!labels?.length || !series?.length || !series.some(item => (item.values || []).some(value => Number(value) !== 0))) {
    drawChartMessage(canvas, 'Não há dados suficientes para exibir o gráfico.');
    const legend = document.getElementById(legendId); if (legend) legend.innerHTML = '';
    return;
  }
  const normalized = series.map((item, index) => ({id: item.id ?? index, label: item.label, values: (item.values || []).map(Number)}));
  const minValue = Math.min(0, ...normalized.flatMap(item => item.values));
  if (minValue >= 0) return drawMultiLineChart(canvasId, labels, normalized, legendId);
  const {ctx, width, height} = prepareCanvas(canvas, Math.max(760, labels.length * 75), 390);
  const pad={left:80,right:24,top:45,bottom:55}, plotW=width-pad.left-pad.right, plotH=height-pad.top-pad.bottom;
  const all=normalized.flatMap(item=>item.values), max=Math.max(...all,1), min=Math.min(...all,-1), range=Math.max(max-min,1);
  const xAt=i=>labels.length===1?pad.left+plotW/2:pad.left+plotW*i/(labels.length-1), yAt=v=>pad.top+(max-v)/range*plotH;
  ctx.font='12px Arial'; ctx.strokeStyle='#dfe5ea'; ctx.fillStyle='#607080';
  for(let i=0;i<=5;i++){const v=max-range*i/5,y=yAt(v);ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(width-pad.right,y);ctx.stroke();ctx.textAlign='right';ctx.fillText(new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0}).format(v),pad.left-8,y+4)}
  const zero=yAt(0);ctx.strokeStyle='#8e9aa5';ctx.beginPath();ctx.moveTo(pad.left,zero);ctx.lineTo(width-pad.right,zero);ctx.stroke();
  normalized.forEach((item,index)=>{const color=colorForDataset(item,index);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=2.5;ctx.beginPath();item.values.forEach((v,i)=>{const x=xAt(i),y=yAt(v);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();item.values.forEach((v,i)=>{ctx.beginPath();ctx.arc(xAt(i),yAt(v),3,0,Math.PI*2);ctx.fill()})});
  labels.forEach((label,i)=>{ctx.save();ctx.translate(xAt(i),height-12);ctx.rotate(-.35);ctx.textAlign='right';ctx.fillStyle='#607080';ctx.fillText(label,0,0);ctx.restore()});
  const legend=document.getElementById(legendId);if(legend){legend.innerHTML='';normalized.forEach((item,index)=>{const span=document.createElement('span');span.className='chart-legend-item';span.innerHTML=`<span class="chart-legend-swatch" style="background:${colorForDataset(item,index)}"></span><span>${item.label}</span>`;legend.appendChild(span)})}
}

function drawScatterChart(canvasId, points, xLabel, yLabel) {
  const canvas=document.getElementById(canvasId); if(!canvas) return;
  if(!points?.length){drawChartMessage(canvas,'Não há dados suficientes para exibir o gráfico.');return}
  const {ctx,width,height}=prepareCanvas(canvas,760,390),pad={left:80,right:25,top:25,bottom:65},plotW=width-pad.left-pad.right,plotH=height-pad.top-pad.bottom;
  const maxX=Math.max(...points.map(p=>Number(p.x)||0),1),maxY=Math.max(...points.map(p=>Number(p.y)||0),1);ctx.font='12px Arial';ctx.strokeStyle='#dfe5ea';ctx.fillStyle='#607080';
  for(let i=0;i<=5;i++){const x=pad.left+plotW*i/5,y=pad.top+plotH-plotH*i/5;ctx.beginPath();ctx.moveTo(x,pad.top);ctx.lineTo(x,pad.top+plotH);ctx.stroke();ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(pad.left+plotW,y);ctx.stroke();ctx.textAlign='center';ctx.fillText((maxX*i/5).toFixed(0),x,height-35);ctx.textAlign='right';ctx.fillText(new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0}).format(maxY*i/5),pad.left-8,y+4)}
  points.forEach((p,index)=>{const x=pad.left+(Number(p.x)||0)/maxX*plotW,y=pad.top+plotH-(Number(p.y)||0)/maxY*plotH;ctx.fillStyle=colorForDataset(p,index);ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();ctx.fillStyle='#33404c';ctx.textAlign='left';ctx.fillText(String(p.label).slice(0,18),x+7,y-5)});ctx.fillStyle='#607080';ctx.textAlign='center';ctx.fillText(xLabel||'',pad.left+plotW/2,height-8);ctx.save();ctx.translate(15,pad.top+plotH/2);ctx.rotate(-Math.PI/2);ctx.fillText(yLabel||'',0,0);ctx.restore();
}
