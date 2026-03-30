import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('monitor');
let frontCamTimer = null;
let backCamTimer = null;
let heatmapData = null;
let heatmapTimer = null;
let showHeatmap = false;

// Cached map state — loaded once, redrawn on pose updates
let cachedMapImg = null;   // decoded Image object
let cachedMapMeta = null;  // {resolution, width, height, origin_x, origin_y}
let cachedMapParams = null; // includes scale
let currentPose = null;
let currentRobotId = null;

export async function initMonitor(ws) {
    ws.on('robot:pose', (data) => {
        if (data.robot_id !== currentRobotId) return;
        currentPose = { x: data.x, y: data.y, theta: data.theta };
        redraw();
        const info = document.getElementById('pose-info');
        if (info) info.textContent = `x: ${data.x.toFixed(2)}, y: ${data.y.toFixed(2)}, \u03b8: ${(data.theta * 180 / Math.PI).toFixed(1)}\u00b0`;
    });
    ws.on('robot:connection', (data) => {
        if (data.robot_id !== currentRobotId) return;
        if (data.state === 'connected') reloadMap();
    });
    await renderMonitor();
}

function reloadMap() {
    if (currentRobotId) loadMap(currentRobotId);
}

async function renderMonitor() {
    container.innerHTML = `<div class="card"><div class="card-header"><h2>\u6a5f\u5668\u4eba\u76e3\u63a7</h2></div><p style="color:var(--text-muted)">\u8f09\u5165\u4e2d...</p></div>`;
    const robots = await api.listRobots();
    const onlineRobots = robots.filter(r => r.online);

    container.innerHTML = `
        <div class="card">
            <div class="card-header"><h2>\u6a5f\u5668\u4eba\u76e3\u63a7</h2></div>
            ${onlineRobots.length === 0 ? '<p style="color:var(--text-muted)">\u7121\u5728\u7dda\u6a5f\u5668\u4eba</p>' : `
            <div class="form-group">
                <label>\u9078\u64c7\u6a5f\u5668\u4eba</label>
                <select id="monitor-robot-select">
                    ${onlineRobots.map(r => `<option value="${r.id}">${r.name} (${r.ip})</option>`).join('')}
                </select>
            </div>
            <div id="monitor-content">
                <div id="map-section" class="monitor-section">
                    <div class="monitor-section-header" style="justify-content:center">
                        <span class="monitor-label">\u5730\u5716 / \u6a5f\u5668\u4eba\u4f4d\u7f6e</span>
                        <span id="pose-info" style="font-size:11px;color:var(--text-muted);margin-left:0.75rem"></span>
                    </div>
                    <div id="map-container" style="position:relative;display:flex;justify-content:center;background:var(--panel-dark);border:1px solid var(--border-medium);border-radius:4px;overflow:hidden;">
                        <canvas id="map-canvas"></canvas>
                    </div>
                    <div style="margin-top:0.75rem;font-size:10px;color:var(--text-muted)">
                        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem">
                            <div style="display:flex;align-items:center;gap:0.5rem">
                                <label style="display:flex;align-items:center;gap:0.25rem;cursor:pointer;font-weight:500;color:var(--text-primary)">
                                    <input type="checkbox" id="heatmap-toggle"> \u7db2\u8def\u6548\u80fd\u5716
                                </label>
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e"></span>&lt;50ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#eab308"></span>50-100ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#f97316"></span>100-200ms
                                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#ef4444"></span>&gt;200ms
                            </div>
                            <button class="btn btn-sm btn-danger" id="clear-heatmap">\u6e05\u9664\u8cc7\u6599</button>
                        </div>
                        <div id="heatmap-stats" style="margin-top:0.25rem">0 \u7b46 | \u5e73\u5747 0ms | \u6700\u5c0f 0ms | \u6700\u5927 0ms</div>
                    </div>
                </div>
                <div class="monitor-cameras">
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">\u524d\u93e1\u982d</span>
                            <button class="btn btn-sm" id="toggle-front-cam">\u958b\u555f</button>
                        </div>
                        <div id="front-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">\u93e1\u982d\u5df2\u95dc\u9589</p>
                        </div>
                    </div>
                    <div class="monitor-section">
                        <div class="monitor-section-header">
                            <span class="monitor-label">\u5f8c\u93e1\u982d</span>
                            <button class="btn btn-sm" id="toggle-back-cam">\u958b\u555f</button>
                        </div>
                        <div id="back-cam-container">
                            <p style="color:var(--text-muted);font-size:11px;padding:1rem;">\u93e1\u982d\u5df2\u95dc\u9589</p>
                        </div>
                    </div>
                </div>
            </div>
            `}
        </div>
    `;

    if (onlineRobots.length === 0) return;

    const sel = container.querySelector('#monitor-robot-select');
    sel.addEventListener('change', () => {
        stopAllStreams();
        heatmapData = null;
        loadMap(sel.value);
        resetCamButtons();
    });

    container.querySelector('#toggle-front-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'front', e.target));
    container.querySelector('#toggle-back-cam').addEventListener('click', (e) => toggleCamera(sel.value, 'back', e.target));

    const heatmapToggle = container.querySelector('#heatmap-toggle');
    const clearBtn = container.querySelector('#clear-heatmap');

    // Load stats on init
    api.getRttHeatmap(sel.value).then(data => {
        updateHeatmapStats(data.stats);
    }).catch(() => {});

    heatmapToggle.addEventListener('change', async () => {
        showHeatmap = heatmapToggle.checked;
        if (showHeatmap) {
            heatmapData = await api.getRttHeatmap(sel.value);
            updateHeatmapStats(heatmapData.stats);
            // Refresh heatmap every 10s while enabled
            heatmapTimer = setInterval(async () => {
                try {
                    heatmapData = await api.getRttHeatmap(sel.value);
                    updateHeatmapStats(heatmapData.stats);
                    redraw();
                } catch {}
            }, 10000);
        } else {
            heatmapData = null;
            if (heatmapTimer) { clearInterval(heatmapTimer); heatmapTimer = null; }
        }
        redraw();
    });
    clearBtn.addEventListener('click', async () => {
        if (confirm('\u78ba\u5b9a\u6e05\u9664\u6240\u6709\u7db2\u8def\u6548\u80fd\u8cc7\u6599\uff1f')) {
            await api.clearRttHeatmap(sel.value);
            heatmapData = null;
            updateHeatmapStats({ count: 0, avg_rtt_ms: 0, min_rtt_ms: 0, max_rtt_ms: 0 });
            showToast('\u7db2\u8def\u6548\u80fd\u8cc7\u6599\u5df2\u6e05\u9664');
            redraw();
        }
    });

    loadMap(sel.value);
}

function rttToColor(rtt) {
    if (rtt < 50) return 'rgba(34, 197, 94, 0.5)';   // green
    if (rtt < 100) return 'rgba(234, 179, 8, 0.5)';   // yellow
    if (rtt < 200) return 'rgba(249, 115, 22, 0.5)';  // orange
    return 'rgba(239, 68, 68, 0.5)';                    // red
}

function updateHeatmapStats(stats) {
    const el = document.getElementById('heatmap-stats');
    if (!el || !stats) return;
    el.textContent = `${stats.count} \u7b46 | \u5e73\u5747 ${stats.avg_rtt_ms}ms | \u6700\u5c0f ${stats.min_rtt_ms}ms | \u6700\u5927 ${stats.max_rtt_ms}ms`;
}

async function loadMap(robotId) {
    stopAllStreams();
    currentRobotId = robotId;
    currentPose = null;
    cachedMapImg = null;
    cachedMapMeta = null;
    cachedMapParams = null;

    try {
        const data = await api.getMap(robotId);
        if (!data.ok) return;

        // Decode image once and cache
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = `data:image/${data.map.format || 'png'};base64,${data.map.image_base64}`;
        });

        cachedMapImg = img;
        cachedMapMeta = data.map;
        currentPose = data.pose;

        // Calculate scale
        const section = document.getElementById('map-section');
        const maxW = Math.min((section ? section.clientWidth - 4 : 500), 500);
        const scale = Math.min(maxW / img.width, 400 / img.height, 1);
        cachedMapParams = { ...data.map, scale };

        const canvas = document.getElementById('map-canvas');
        if (canvas) {
            canvas.width = img.width * scale;
            canvas.height = img.height * scale;
        }

        redraw();
    } catch (e) {
        console.error('Map load error:', e);
    }
}

function worldToPixel(wx, wy, map, scale) {
    const res = map.resolution || 0.025;
    const ox = map.origin_x || 0;
    const oy = map.origin_y || 0;
    const mapH = map.height;
    const px = ((wx - ox) / res) * scale;
    const py = ((mapH - (wy - oy) / res)) * scale;
    return [px, py];
}

function redraw() {
    const canvas = document.getElementById('map-canvas');
    if (!canvas || !cachedMapImg || !cachedMapParams) return;
    const ctx = canvas.getContext('2d');
    const scale = cachedMapParams.scale;

    // 1. Draw cached map image
    ctx.drawImage(cachedMapImg, 0, 0, canvas.width, canvas.height);

    // 2. Draw RTT heatmap overlay
    if (showHeatmap && heatmapData && heatmapData.points) {
        for (const pt of heatmapData.points) {
            const [px, py] = worldToPixel(pt.x, pt.y, cachedMapParams, scale);
            ctx.beginPath();
            ctx.arc(px, py, 4, 0, Math.PI * 2);
            ctx.fillStyle = rttToColor(pt.rtt_ms);
            ctx.fill();
        }
    }

    // 3. Draw robot position
    if (currentPose) {
        const [px, py] = worldToPixel(currentPose.x, currentPose.y, cachedMapParams, scale);

        ctx.beginPath();
        ctx.arc(px, py, 8, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(220, 53, 69, 0.8)';
        ctx.fill();
        ctx.strokeStyle = 'white';
        ctx.lineWidth = 2;
        ctx.stroke();

        const arrowLen = 16;
        const angle = -currentPose.theta;
        const ax = px + Math.cos(angle) * arrowLen;
        const ay = py - Math.sin(angle) * arrowLen;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ax, ay);
        ctx.strokeStyle = 'rgba(220, 53, 69, 0.9)'; ctx.lineWidth = 3; ctx.stroke();
        const headLen = 6;
        ctx.beginPath();
        ctx.moveTo(ax, ay); ctx.lineTo(ax + Math.cos(angle + Math.PI * 0.8) * headLen, ay - Math.sin(angle + Math.PI * 0.8) * headLen);
        ctx.moveTo(ax, ay); ctx.lineTo(ax + Math.cos(angle - Math.PI * 0.8) * headLen, ay - Math.sin(angle - Math.PI * 0.8) * headLen);
        ctx.stroke();

        const info = document.getElementById('pose-info');
        if (info) info.textContent = `x: ${currentPose.x.toFixed(2)}, y: ${currentPose.y.toFixed(2)}, \u03b8: ${(currentPose.theta * 180 / Math.PI).toFixed(1)}\u00b0`;
    }
}

async function toggleCamera(robotId, camera, btn) {
    const containerId = camera === 'front' ? 'front-cam-container' : 'back-cam-container';
    const camContainer = document.getElementById(containerId);
    if (btn.textContent === '\u958b\u555f') {
        btn.textContent = '\u95dc\u9589';
        btn.classList.add('btn-danger');
        btn.classList.remove('btn-success');
        startCameraStream(robotId, camera, camContainer);
    } else {
        btn.textContent = '\u958b\u555f';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-success');
        stopCameraStream(camera);
        await api.stopCamera(robotId, camera);
        camContainer.innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">\u93e1\u982d\u5df2\u95dc\u9589</p>';
    }
}

function startCameraStream(robotId, camera, camContainer) {
    const streamUrl = `/api/robots/${robotId}/camera/${camera}/stream`;
    camContainer.innerHTML = `<img id="${camera}-cam-img" src="${streamUrl}" style="width:100%;max-width:400px;border-radius:4px;display:block;" />`;
    if (camera === 'front') frontCamTimer = 1;
    else backCamTimer = 1;
}

function stopCameraStream(camera) {
    const img = document.getElementById(camera + '-cam-img');
    if (img) img.removeAttribute('src');
    if (camera === 'front') frontCamTimer = null;
    else backCamTimer = null;
}

function stopAllStreams() {
    if (heatmapTimer) { clearInterval(heatmapTimer); heatmapTimer = null; }
    if (frontCamTimer) { clearInterval(frontCamTimer); frontCamTimer = null; }
    if (backCamTimer) { clearInterval(backCamTimer); backCamTimer = null; }
}

function resetCamButtons() {
    ['toggle-front-cam', 'toggle-back-cam'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) { btn.textContent = '\u958b\u555f'; btn.classList.remove('btn-danger'); btn.classList.add('btn-success'); }
    });
    document.getElementById('front-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">\u93e1\u982d\u5df2\u95dc\u9589</p>';
    document.getElementById('back-cam-container').innerHTML = '<p style="color:var(--text-muted);font-size:11px;padding:1rem;">\u93e1\u982d\u5df2\u95dc\u9589</p>';
}
