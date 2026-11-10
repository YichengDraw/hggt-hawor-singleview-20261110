'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const controllers = new Set();
  let metricDefinitions = [];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function safeUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, document.baseURI);
      return ['http:', 'https:', 'file:'].includes(url.protocol) ? value : null;
    } catch (_) { return null; }
  }

  function link(label, href, className = '') {
    const a = el('a', className, label);
    const url = safeUrl(href);
    if (!url) return el('span', 'empty-cell', label);
    a.href = url;
    if (/^https?:\/\//i.test(url)) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    }
    return a;
  }

  function addLinks(container, entries) {
    for (const item of entries || []) {
      if (item && safeUrl(item.href || item.url)) container.append(link(item.label || item.href || item.url, item.href || item.url));
    }
  }

  function paragraphs(container, values) {
    for (const value of values || []) if (value) container.append(el('p', '', value));
  }

  function methodLabel(method) {
    const span = el('span', 'method-name');
    const family = String(method).toLowerCase().includes('hggt') ? 'hggt' : String(method).toLowerCase().includes('hawor') ? 'hawor' : '';
    span.append(el('i', `method-dot ${family}`), document.createTextNode(method));
    return span;
  }

  function formatValue(value, definition) {
    if (value === null || value === undefined || (typeof value === 'number' && !Number.isFinite(value))) return '—';
    if (typeof value !== 'number') return String(value);
    const decimals = definition.decimals !== undefined ? definition.decimals : /frames|count|samples/.test(definition.key) ? 0 : 2;
    return value.toLocaleString('zh-CN', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
  }

  function metricTable(rows, withSample) {
    const present = metricDefinitions.filter(d => rows.some(r => r.values && r.values[d.key] !== undefined));
    if (!present.length || !rows.length) return null;
    const wrap = el('div', 'table-scroll');
    const table = el('table', 'metrics-table');
    const head = el('thead');
    const tr = el('tr');
    if (withSample) tr.append(el('th', '', '样例'));
    tr.append(el('th', 'method', '方法'));
    for (const d of present) {
      const th = el('th', '', `${d.label || d.key}${d.unit ? ` (${d.unit})` : ''}`);
      if (d.description) th.title = d.description;
      th.scope = 'col';
      tr.append(th);
    }
    head.append(tr);
    table.append(head);
    const body = el('tbody');
    let previousId = null;
    for (const row of rows) {
      const r = el('tr', withSample && previousId !== null && previousId !== row.sample_id ? 'group-start' : '');
      if (withSample) {
        const td = el('td');
        td.append(link(row.sample_title || row.sample_id, `#${row.sample_id}`));
        r.append(td);
      }
      const methodCell = el('td', 'method');
      methodCell.append(methodLabel(row.method || '未命名方法'));
      r.append(methodCell);
      for (const d of present) {
        const value = row.values ? row.values[d.key] : undefined;
        r.append(el('td', value === undefined || value === null ? 'empty-cell' : '', formatValue(value, d)));
      }
      body.append(r);
      previousId = row.sample_id;
    }
    table.append(body);
    wrap.append(table);
    return wrap;
  }

  function normalizeMedia(value) {
    return typeof value === 'string' ? {src: value} : value;
  }

  function makePlayer(sample) {
    const media = sample.media || {};
    const composite = normalizeMedia(media.comparison);
    let clips;
    if (composite && safeUrl(composite.src)) {
      clips = [{key: 'comparison', label: composite.label || '输入 / HGGT / HaWoR · 同帧对比', ...composite}];
    } else {
      clips = [['input', '原始 RGB'], ['hggt', 'HGGT'], ['hawor', 'HaWoR']]
        .map(([key, label]) => ({key, label, ...normalizeMedia(media[key])}))
        .filter(m => safeUrl(m.src));
    }
    if (!clips.length) return el('div', 'placeholder', sample.media_pending_message || '该序列的视频尚未导出。');

    const wrapper = el('div', 'video-player');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('aria-label', `${sample.title || sample.id} 同步视频播放器`);
    const grid = el('div', `video-grid${clips[0].key === 'comparison' ? ' composite' : ''}`);
    grid.style.setProperty('--columns', clips.length);
    const videos = [];
    const errors = new Set();
    for (const clip of clips) {
      const figure = el('figure', 'video-cell');
      const caption = el('figcaption');
      caption.append(el('span', '', clip.label), link('打开视频 ↗', clip.src));
      const video = el('video');
      video.src = safeUrl(clip.src);
      video.preload = 'metadata';
      video.playsInline = true;
      video.muted = true;
      video.controls = false;
      video.setAttribute('aria-label', clip.label);
      if (safeUrl(clip.poster)) video.poster = clip.poster;
      if (clip.width && clip.height) video.style.setProperty('--video-ratio', `${clip.width}/${clip.height}`);
      video.addEventListener('error', () => {
        if (errors.has(video)) return;
        errors.add(video);
        figure.append(el('p', 'media-error', '视频加载失败，可点击右上角链接检查原文件。'));
      });
      figure.append(caption, video);
      grid.append(figure);
      videos.push(video);
    }
    wrapper.append(grid);

    const toolbar = el('div', 'player-toolbar');
    const transport = el('div', 'transport');
    const playButton = el('button', 'play', '▶ 播放');
    playButton.type = 'button';
    playButton.setAttribute('aria-label', '播放同步视频');
    const previous = el('button', '', '‹');
    previous.type = 'button';
    previous.title = '上一帧（←）';
    previous.setAttribute('aria-label', '上一帧');
    const next = el('button', '', '›');
    next.type = 'button';
    next.title = '下一帧（→）';
    next.setAttribute('aria-label', '下一帧');
    const frameLabel = el('label', 'frame-label', '第');
    const frameInput = el('input', 'frame-input');
    frameInput.type = 'number';
    frameInput.min = '1';
    frameInput.step = '1';
    frameInput.value = '1';
    frameInput.setAttribute('aria-label', '跳转到回放帧');
    const frameTotal = el('span', '', '/ — 帧');
    frameLabel.append(frameInput, frameTotal);
    const speedLabel = el('label', 'speed-label', '速度');
    const speed = el('select');
    speed.setAttribute('aria-label', '播放速度');
    for (const v of [0.25, 0.5, 1, 2]) {
      const option = el('option', '', `${v}×`);
      option.value = String(v);
      option.selected = v === 1;
      speed.append(option);
    }
    speedLabel.append(speed);
    const fullscreen = el('button', '', '全屏');
    fullscreen.type = 'button';
    fullscreen.setAttribute('aria-label', '全屏查看对比');
    fullscreen.hidden = !wrapper.requestFullscreen;
    fullscreen.addEventListener('click', async () => {
      try {
        if (document.fullscreenElement === wrapper) await document.exitFullscreen();
        else await wrapper.requestFullscreen();
      } catch (_) { /* The direct video link remains available if fullscreen is blocked. */ }
    });
    const timeLabel = el('span', 'time-label', '0.00 s');
    transport.append(playButton, previous, next, frameLabel, speedLabel, fullscreen, timeLabel);
    const timeline = el('input', 'timeline');
    timeline.type = 'range';
    timeline.min = '0';
    timeline.step = '1';
    timeline.value = '0';
    timeline.setAttribute('aria-label', '共享帧时间轴');
    toolbar.append(transport, timeline);
    wrapper.append(toolbar);
    const caption = el('p', 'player-caption');
    caption.append(el('span', '', sample.legend || '视频按相同帧顺序导出；下方时间轴控制全部画面。'), el('span', '', '← / → 逐帧 · 空格播放'));
    wrapper.append(caption);
    const message = el('p', 'player-message');
    toolbar.append(message);
    message.hidden = true;

    const master = videos[0];
    const fps = Number(sample.fps) > 0 ? Number(sample.fps) : 30;
    const frameTimes = Array.isArray(sample.video_frame_timestamps_s) ? sample.video_frame_timestamps_s : null;
    let frameCount = Number(sample.frame_count) > 0 ? Number(sample.frame_count) : 1;
    let currentFrame = 0;
    let playing = false;
    let callback = null;
    let usesVideoCallback = false;
    const frameTime = (frame) => frameTimes && Number.isFinite(frameTimes[frame]) ? frameTimes[frame] : frame / fps;
    const duration = () => frameTimes && frameTimes.length ? frameTimes[frameTimes.length - 1] + 1 / fps : frameCount / fps;
    const frameAt = (time) => {
      if (!frameTimes) return Math.min(frameCount - 1, Math.max(0, Math.floor(time * fps + 0.001)));
      let lo = 0, hi = frameTimes.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (frameTimes[mid] <= time + 0.0001) lo = mid + 1; else hi = mid; }
      return Math.min(frameCount - 1, Math.max(0, lo - 1));
    };

    function updateReadout(frame) {
      currentFrame = Math.min(frameCount - 1, Math.max(0, frame));
      timeline.max = String(Math.max(0, frameCount - 1));
      timeline.value = String(currentFrame);
      frameInput.max = String(frameCount);
      frameInput.value = String(currentFrame + 1);
      frameTotal.textContent = `/ ${frameCount} 帧`;
      let clock = `${frameTime(currentFrame).toFixed(2)} / ${duration().toFixed(2)} s`;
      if (Array.isArray(sample.source_frame_ids) && sample.source_frame_ids[currentFrame] !== undefined) clock += ` · 源帧 ${sample.source_frame_ids[currentFrame]}`;
      else if (Number.isFinite(sample.source_frame_start)) clock += ` · 源帧 ${sample.source_frame_start + currentFrame}`;
      timeLabel.textContent = clock;
      timeline.setAttribute('aria-valuetext', `第 ${currentFrame + 1} 帧，共 ${frameCount} 帧`);
    }

    function cancelTick() {
      if (callback === null) return;
      if (usesVideoCallback && master.cancelVideoFrameCallback) master.cancelVideoFrameCallback(callback);
      else cancelAnimationFrame(callback);
      callback = null;
    }

    function pause() {
      playing = false;
      for (const video of videos) video.pause();
      cancelTick();
      playButton.textContent = '▶ 播放';
      playButton.setAttribute('aria-label', '播放同步视频');
    }

    function seek(frame) {
      pause();
      const clamped = Math.max(0, Math.min(frameCount - 1, Math.round(frame)));
      // Seek inside the displayed frame to avoid MP4 boundary rounding.
      const time = frameTime(clamped) + 0.1 / fps;
      for (const video of videos) {
        try { video.currentTime = Math.min(time, Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.001) : time); } catch (_) { /* Metadata may still be loading. */ }
      }
      updateReadout(clamped);
    }

    function tick() {
      if (!playing) return;
      const time = master.currentTime;
      updateReadout(frameAt(time));
      for (const video of videos.slice(1)) {
        if (!errors.has(video) && Math.abs(video.currentTime - time) > Math.max(0.04, 1.25 / fps)) video.currentTime = time;
      }
      scheduleTick();
    }

    function scheduleTick() {
      if (master.requestVideoFrameCallback) {
        usesVideoCallback = true;
        callback = master.requestVideoFrameCallback(tick);
      } else {
        usesVideoCallback = false;
        callback = requestAnimationFrame(tick);
      }
    }

    async function play() {
      for (const controller of controllers) if (controller !== control) controller.pause();
      if (errors.has(master)) return;
      if (master.ended || currentFrame >= frameCount - 1) seek(0);
      const time = master.currentTime;
      for (const video of videos) {
        if (errors.has(video)) continue;
        video.playbackRate = Number(speed.value);
        if (video !== master && Math.abs(video.currentTime - time) > 0.01) video.currentTime = time;
      }
      playing = true;
      playButton.textContent = 'Ⅱ 暂停';
      playButton.setAttribute('aria-label', '暂停同步视频');
      message.hidden = true;
      const results = await Promise.allSettled(videos.filter(v => !errors.has(v)).map(v => v.play()));
      if (results.some(r => r.status === 'rejected')) {
        pause();
        message.textContent = '浏览器未能开始播放，请稍候重试或直接打开视频。';
        message.hidden = false;
        return;
      }
      if (playing) scheduleTick();
    }

    const control = {pause, seek, element: wrapper};
    controllers.add(control);
    playButton.addEventListener('click', () => playing ? pause() : play());
    previous.addEventListener('click', () => seek(currentFrame - 1));
    next.addEventListener('click', () => seek(currentFrame + 1));
    timeline.addEventListener('input', () => seek(Number(timeline.value)));
    frameInput.addEventListener('change', () => seek(Number(frameInput.value) - 1));
    speed.addEventListener('change', () => { for (const video of videos) video.playbackRate = Number(speed.value); });
    master.addEventListener('loadedmetadata', () => {
      if (!(Number(sample.frame_count) > 0)) frameCount = Math.max(1, Math.round(master.duration * fps));
      updateReadout(currentFrame);
    });
    master.addEventListener('ended', () => { pause(); updateReadout(frameCount - 1); });
    wrapper.addEventListener('keydown', (event) => {
      if (['INPUT', 'SELECT', 'BUTTON', 'A'].includes(event.target.tagName)) return;
      if (event.key === 'ArrowLeft') { event.preventDefault(); seek(currentFrame - 1); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); seek(currentFrame + 1); }
      else if (event.code === 'Space') { event.preventDefault(); playing ? pause() : play(); }
    });
    updateReadout(0);
    return wrapper;
  }

  function makeSample(sample) {
    const section = el('section', 'sample-card');
    section.id = sample.id;
    section.dataset.dataset = sample.dataset || '其他';
    const heading = el('div', 'sample-heading');
    const title = el('h2', '', sample.title || sample.id);
    if (sample.dataset) title.append(el('span', 'dataset-label', sample.dataset));
    const status = sample.status || (sample.media ? 'complete' : 'pending');
    const labels = {complete: '可回放', running: '处理中', pending: '待完成', unavailable: '待补充'};
    heading.append(title, el('span', `sample-status${status === 'complete' ? '' : ' pending'}`, sample.status_label || labels[status] || status));
    section.append(heading);
    const identity = [sample.sequence || sample.sequence_id, sample.camera ? `相机 ${sample.camera}` : ''].filter(Boolean).join(' · ');
    if (identity) section.append(el('p', 'sequence', identity));
    const detail = [sample.frame_count ? `${sample.frame_count} 帧` : '', sample.fps ? `${sample.fps} fps` : '', sample.description || ''].filter(Boolean).join(' · ');
    if (detail) section.append(el('p', 'sample-description', detail));
    section.append(makePlayer(sample));
    if (sample.notes && sample.notes.length) { const notes = el('div', 'sample-notes'); paragraphs(notes, sample.notes); section.append(notes); }
    const links = el('div', 'link-list sample-links');
    addLinks(links, sample.links);
    if (links.childNodes.length) section.append(links);
    if (sample.metrics && sample.metrics.length) {
      const metrics = metricTable(sample.metrics, false);
      if (metrics) {
        const block = el('div', 'sample-metrics');
        block.append(el('h3', '', sample.metrics_title || '同帧评价'), metrics);
        if (sample.metrics_note) block.append(el('p', 'footnotes', sample.metrics_note));
        section.append(block);
      }
    } else if (sample.metrics_pending_message) section.append(el('p', 'footnotes', sample.metrics_pending_message));
    if (sample.keyframes && sample.keyframes.length) {
      const frames = el('div', 'keyframes');
      for (const keyframe of sample.keyframes) {
        if (!safeUrl(keyframe.src)) continue;
        const figure = el('figure');
        const label = keyframe.label || (Number.isFinite(keyframe.frame_index) ? `回放第 ${keyframe.frame_index + 1} 帧` : '关键帧');
        const a = link('', keyframe.src);
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        const img = el('img');
        img.src = keyframe.src;
        img.alt = `${sample.title || sample.id} · ${label}`;
        img.loading = 'lazy';
        a.append(img);
        figure.append(a, el('figcaption', '', label));
        frames.append(figure);
      }
      section.append(frames);
    }
    return section;
  }

  function render(manifest) {
    const samples = Array.isArray(manifest.samples) ? manifest.samples : [];
    metricDefinitions = Array.isArray(manifest.metric_definitions) ? manifest.metric_definitions : [];
    if (manifest.title) { $('page-title').textContent = manifest.title; document.title = manifest.title; }
    if (manifest.subtitle) $('page-subtitle').textContent = manifest.subtitle;
    if (manifest.updated_at) $('updated-at').textContent = `更新 ${manifest.updated_at}`;
    paragraphs($('summary'), manifest.summary);
    addLinks($('top-links'), manifest.downloads);
    if (Array.isArray(manifest.protocol) && manifest.protocol.length) {
      for (const item of manifest.protocol) {
        const wrapper = el('div');
        wrapper.append(el('dt', '', item.label), el('dd', '', item.value));
        $('protocol').append(wrapper);
      }
      $('protocol-section').hidden = false;
    }
    paragraphs($('scope-notes'), manifest.scope_notes);
    if (manifest.scope_notes && manifest.scope_notes.length) $('protocol-section').hidden = false;

    const allRows = samples.flatMap(s => (s.metrics || []).map(r => ({...r, sample_id: s.id, sample_title: s.short_title || s.title || s.id})));
    const table = metricTable(allRows, true);
    if (table) {
      $('metrics-summary').append(table);
      $('metrics-section').hidden = false;
      for (const d of metricDefinitions) if (d.description) $('metric-definitions').append(el('p', '', `${d.label || d.key}：${d.description}`));
      if (!$('metric-definitions').childNodes.length) $('metric-guide').hidden = true;
      if (manifest.metrics_note) $('metrics-summary').append(el('p', 'footnotes', manifest.metrics_note));
    }
    $('samples').replaceChildren();
    if (!samples.length) $('samples').append(el('p', 'placeholder', '实验记录尚未生成。完成后将在这里显示真实视频和评价结果。'));
    for (const sample of samples) {
      $('samples').append(makeSample(sample));
      $('sample-nav').append(link(sample.short_title || sample.title || sample.id, `#${sample.id}`));
    }

    const datasets = [...new Set(samples.map(s => s.dataset || '其他'))];
    function applyFilter(dataset) {
      for (const card of document.querySelectorAll('.sample-card')) {
        card.hidden = dataset !== '全部' && card.dataset.dataset !== dataset;
        if (card.hidden) for (const control of controllers) if (card.contains(control.element)) control.pause();
      }
      for (const button of $('dataset-filters').children) button.setAttribute('aria-pressed', String(button.dataset.dataset === dataset));
    }
    if (datasets.length > 1) {
      for (const dataset of ['全部', ...datasets]) {
        const button = el('button', 'filter-button', dataset);
        button.type = 'button';
        button.dataset.dataset = dataset;
        button.setAttribute('aria-pressed', String(dataset === '全部'));
        button.addEventListener('click', () => applyFilter(dataset));
        $('dataset-filters').append(button);
      }
    }
    for (const anchor of document.querySelectorAll('a[href^="#"]')) {
      anchor.addEventListener('click', () => applyFilter('全部'));
    }
    for (const source of manifest.sources || []) {
      const li = el('li');
      li.append(link(source.label || source.url, source.url || source.href));
      if (source.note) li.append(el('span', 'source-note', source.note));
      $('sources').append(li);
    }
    $('sources-section').hidden = !$('sources').childNodes.length;
    try {
      if (location.hash) requestAnimationFrame(() => $(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView());
    } catch (_) { /* Invalid hashes do not block rendering. */ }
  }

  document.addEventListener('visibilitychange', () => { if (document.hidden) for (const controller of controllers) controller.pause(); });
  fetch('manifest.json', {cache: 'no-store'})
    .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
    .then(render)
    .catch(error => {
      const message = el('p', 'error-banner', `实验记录读取失败（${error.message}）。请刷新页面，或直接下载 `);
      message.append(link('manifest.json', 'manifest.json'), document.createTextNode(' 查看。'));
      $('samples').replaceChildren(message);
    });
})();
