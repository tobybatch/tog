import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import { EdgeCurvedArrowProgram as EdgeCurveProgram } from "@sigma/edge-curve";
import { NodeBorderProgram } from '@sigma/node-border';

let sigmaInstance = null;
let currentData = null;
let graphData = null;
let highlightedNodes = new Set();
let highlightedEdges = new Set();
let hoveredNode = null;

function showError(message) {
    const errorEl = document.getElementById('error');
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.style.display = 'block';
    setTimeout(() => { errorEl.style.display = 'none'; }, 5000);
}

function updateInfo(nodeCount, linkCount) {
    const infoEl = document.getElementById('info');
    if (infoEl) infoEl.textContent = `${nodeCount} nodes · ${linkCount} edges`;
}

function getColorForType(type) {
    if (!type) return [99, 102, 241];
    let hash = 0;
    for (let i = 0; i < type.length; i++) {
        hash = ((hash << 5) - hash) + type.charCodeAt(i);
        hash = hash & hash;
    }
    const hue = Math.abs(hash) % 360;
    const saturation = 65 + (Math.abs(hash >> 8) % 20);
    const lightness = 50 + (Math.abs(hash >> 16) % 15);
    const h = hue / 360, s = saturation / 100, l = lightness / 100;
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs((h * 6) % 2 - 1));
    const m = l - c / 2;
    let r = 0, g = 0, b = 0;
    if (h < 1/6) { r = c; g = x; b = 0; }
    else if (h < 2/6) { r = x; g = c; b = 0; }
    else if (h < 3/6) { r = 0; g = c; b = x; }
    else if (h < 4/6) { r = 0; g = x; b = c; }
    else if (h < 5/6) { r = x; g = 0; b = c; }
    else { r = c; g = 0; b = x; }
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => Math.round(Math.min(255, x)).toString(16).padStart(2, '0')).join('');
}

function brighten(hex, factor) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return rgbToHex(r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor);
}

export async function loadGraph() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'flex';

    try {
        const response = await fetch('/api/graph');
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to fetch ontology graph');
        }

        const data = await response.json();
        currentData = data;

        const typeCounts = data.nodes.reduce((acc, n) => {
            acc[n.type] = (acc[n.type] || 0) + 1;
            return acc;
        }, {});

        updateFilterOptions(typeCounts);
        updateLegend(typeCounts);

        const analysis = data.analysis || {};
        const maxConnectivity = Math.max(...Object.values(analysis).map(a => a.connectivity), 1);

        if (sigmaInstance) { sigmaInstance.kill(); sigmaInstance = null; }

        graphData = new Graph({ multi: true, type: 'directed' });

        data.nodes.forEach(node => {
            const rgb = getColorForType(node.type);
            const connectivity = analysis[node.id]?.connectivity || 0;
            const size = 5 + (connectivity / maxConnectivity) * 16;
            const color = rgbToHex(rgb[0], rgb[1], rgb[2]);

            graphData.addNode(node.id, {
                label: node.label || node.id,
                size,
                color,
                borderColor: brighten(color, 0.4),
                borderSize: 0.15,
                x: Math.random() * 1000 - 500,
                y: Math.random() * 1000 - 500,
            });
        });

        data.links.forEach(link => {
            if (graphData.hasNode(link.source) && graphData.hasNode(link.target)) {
                try {
                    graphData.addEdge(link.source, link.target, {
                        label: link.type || '',
                        type: 'curved',
                        color: 'rgba(99,102,241,0.35)',
                        size: 1.5,
                    });
                } catch (_) {}
            }
        });

        forceAtlas2.assign(graphData, {
            iterations: 250,
            settings: { ...forceAtlas2.inferSettings(graphData), gravity: 1, scalingRatio: 4, slowDown: 10 }
        });

        const container = document.getElementById('graph');
        sigmaInstance = new Sigma(graphData, container, {
            renderEdgeLabels: true,
            defaultEdgeType: 'curved',
            defaultNodeType: 'bordered',
            edgeProgramClasses: { curved: EdgeCurveProgram },
            nodeProgramClasses: { bordered: NodeBorderProgram },
            labelFont: '"Inter", sans-serif',
            labelColor: { color: '#e2e8f0' },
            labelSize: 11,
            edgeLabelFont: '"Inter", sans-serif',
            edgeLabelColor: { color: '#818cf8' },
            edgeLabelSize: 8,
            nodeReducer: (node, data) => {
                const res = { ...data };
                const isHovered = hoveredNode === node;
                const isHighlighted = highlightedNodes.size === 0 || highlightedNodes.has(node);
                if (!isHighlighted) {
                    return { ...res, color: '#0f172a', borderColor: '#1e293b', label: null, size: data.size * 0.4, zIndex: 0 };
                }
                if (isHovered) {
                    return { ...res, color: brighten(data.color, 0.5), borderColor: '#ffffff', size: data.size * 1.3, zIndex: 10 };
                }
                return { ...res, zIndex: 1 };
            },
            edgeReducer: (edge, data) => {
                const srcOrTgt = graphData.source(edge) === hoveredNode || graphData.target(edge) === hoveredNode;
                if (highlightedEdges.size > 0) {
                    if (!highlightedEdges.has(edge)) return { ...data, color: 'rgba(10,14,26,0.15)', label: null };
                    return { ...data, color: 'rgba(129,140,248,0.85)', size: 2.5, label: data.label };
                }
                if (srcOrTgt) return { ...data, color: 'rgba(129,140,248,0.7)', size: 2.5, label: data.label };
                return data;
            }
        });

        sigmaInstance.on('enterNode', ({ node }) => {
            hoveredNode = node;
            sigmaInstance.refresh();
            container.style.cursor = 'pointer';
        });

        sigmaInstance.on('leaveNode', () => {
            hoveredNode = null;
            sigmaInstance.refresh();
            container.style.cursor = 'default';
        });

        sigmaInstance.on('clickNode', ({ node }) => {
            const nodeIndex = currentData.nodes.findIndex(n => n.id === node);
            if (nodeIndex >= 0) {
                showDetailedInfo(nodeIndex);
                highlightNodeNeighborhood(node);
            }
        });

        sigmaInstance.on('clickStage', () => { clearHighlight(); });

        setupSearch();
        updateInfo(data.nodes.length, data.links.length);
    } catch (error) {
        showError('Failed to render visualization: ' + error.message);
    } finally {
        if (overlay) overlay.style.display = 'none';
    }
}

function highlightNodeNeighborhood(nodeId) {
    if (!sigmaInstance || !graphData) return;
    highlightedNodes = new Set([nodeId]);
    highlightedEdges = new Set();
    graphData.forEachEdge((edge, _attrs, source, target) => {
        if (source === nodeId || target === nodeId) {
            highlightedEdges.add(edge);
            highlightedNodes.add(source);
            highlightedNodes.add(target);
        }
    });
    sigmaInstance.refresh();
}

function clearHighlight() {
    highlightedNodes.clear();
    highlightedEdges.clear();
    if (sigmaInstance) sigmaInstance.refresh();
}

function showDetailedInfo(index) {
    const panel = document.getElementById('details-panel');
    const content = document.getElementById('details-content');
    const node = currentData.nodes[index];
    if (!node) return;

    const rgb = getColorForType(node.type);
    const typeColor = rgbToHex(rgb[0], rgb[1], rgb[2]);

    let html = `<h3 style="margin-bottom:0.5rem;color:#fff;">${node.label || node.id}</h3>`;
    html += `<span class="type" style="background:${typeColor}22;color:${typeColor};border:1px solid ${typeColor}44;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:600;">${node.type}</span>`;

    if (node.description) {
        html += `<p style="margin-top:1rem;color:#cbd5e1;line-height:1.6">${node.description}</p>`;
    }

    if (node.properties?.dataProperties?.length > 0) {
        html += `<div style="margin-top:1.5rem">
            <h4 style="font-size:0.7rem;text-transform:uppercase;color:#64748b;margin-bottom:0.75rem;font-weight:600;">Data Properties</h4>`;
        node.properties.dataProperties.forEach(prop => {
            html += `<div style="margin-bottom:0.5rem;padding:0.5rem;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);border-radius:6px;">
                <p style="color:#e2e8f0;font-size:0.8rem;font-weight:500;">${prop.name} <span style="color:#64748b;font-weight:400;">(${prop.data_type})</span></p>
                ${prop.description ? `<p style="color:#94a3b8;font-size:0.75rem;margin-top:0.25rem;">\${prop.description}</p>` : ''}
            </div>`;
        });
        html += `</div>`;
    }

    html += formatRelationships(node.id);

    content.innerHTML = html;
    panel.classList.add('open');
    document.getElementById('graph').classList.add('with-panel');
    document.getElementById('controls').classList.add('with-panel');
}

function formatRelationships(nodeId) {
    if (!currentData?.links) return '';
    const outgoing = currentData.links.filter(l => l.source === nodeId);
    const incoming = currentData.links.filter(l => l.target === nodeId);

    if (outgoing.length === 0 && incoming.length === 0) return '';

    let html = '<div style="margin-top:1.5rem"><h4 style="font-size:0.7rem;text-transform:uppercase;color:#64748b;margin-bottom:0.75rem;font-weight:600;">Relationships</h4>';

    outgoing.forEach(rel => {
        const targetNode = currentData.nodes.find(n => n.id === rel.target);
        const targetLabel = targetNode ? (targetNode.label || targetNode.id) : rel.target;
        html += `<div style="margin-bottom:0.4rem;padding:0.5rem;background:rgba(99,102,241,0.08);border-radius:6px;border-left:2px solid rgba(99,102,241,0.5);">
            <p style="font-size:0.8rem;color:#e2e8f0;"><span style="color:#818cf8;font-weight:500;">${rel.type}</span> → ${targetLabel}</p>
            ${rel.properties?.description ? `<p style="font-size:0.75rem;color:#94a3b8;margin-top:0.2rem;">\${rel.properties.description}</p>` : ''}
        </div>`;
    });

    incoming.forEach(rel => {
        const sourceNode = currentData.nodes.find(n => n.id === rel.source);
        const sourceLabel = sourceNode ? (sourceNode.label || sourceNode.id) : rel.source;
        html += `<div style="margin-bottom:0.4rem;padding:0.5rem;background:rgba(99,102,241,0.08);border-radius:6px;border-left:2px solid rgba(99,102,241,0.5);">
            <p style="font-size:0.8rem;color:#e2e8f0;">${sourceLabel} → <span style="color:#818cf8;font-weight:500;">${rel.type}</span></p>
            ${rel.properties?.description ? `<p style="font-size:0.75rem;color:#94a3b8;margin-top:0.2rem;">\${rel.properties.description}</p>` : ''}
        </div>`;
    });

    html += '</div>';
    return html;
}

export function closeDetailsPanel() {
    document.getElementById('details-panel')?.classList.remove('open');
    document.getElementById('graph')?.classList.remove('with-panel');
    document.getElementById('controls')?.classList.remove('with-panel');
    clearHighlight();
}

function setupSearch() {
    document.getElementById('search')?.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        if (!query) { clearHighlight(); return; }

        highlightedNodes = new Set(
            currentData.nodes
                .filter(n => n.label?.toLowerCase().includes(query) || n.id?.toLowerCase().includes(query) || n.description?.toLowerCase().includes(query))
                .map(n => n.id)
        );

        if (highlightedNodes.size > 0) {
            highlightedEdges.clear();
            sigmaInstance.refresh();
            if (highlightedNodes.size === 1) {
                const nodeId = [...highlightedNodes][0];
                const d = sigmaInstance.getNodeDisplayData(nodeId);
                if (d) sigmaInstance.getCamera().animate({ x: d.x, y: d.y, ratio: 0.3 }, { duration: 500 });
            }
        } else {
            clearHighlight();
        }
    });
}

function updateFilterOptions(typeCounts) {
    const select = document.getElementById('filter');
    if (!select) return;
    select.innerHTML = '<option value="">All types</option>';
    Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).forEach(([type, count]) => {
        const opt = document.createElement('option');
        opt.value = type;
        opt.textContent = `${type} (${count})`;
        select.appendChild(opt);
    });
}

function updateLegend(typeCounts) {
    const legend = document.getElementById('legend');
    if (!legend) return;
    legend.innerHTML = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([type]) => {
        const rgb = getColorForType(type);
        const color = rgbToHex(rgb[0], rgb[1], rgb[2]);
        return `<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.2rem;"><span style="width:8px;height:8px;border-radius:50%;background:${color};box-shadow:0 0 6px ${color}88;"></span><span style="font-size:0.7rem;color:#94a3b8;font-weight:500;">${type}</span></div>`;
    }).join('');
}

export function applyFilter() {
    const filter = document.getElementById('filter')?.value;
    if (!filter) { clearHighlight(); return; }
    highlightedNodes = new Set(currentData.nodes.filter(n => n.type === filter).map(n => n.id));
    highlightedEdges.clear();
    sigmaInstance.refresh();
}

// Bind methods explicitly to window for browser execution
if (typeof window !== 'undefined') {
    window.loadGraph = loadGraph;
    window.closeDetailsPanel = closeDetailsPanel;
    window.applyFilter = applyFilter;

    window.addEventListener('DOMContentLoaded', () => {
        loadGraph();
    });
}