/**
 * Visualizes a Turtle (TTL) file or string in a DOM container using Sigma.js and Graphology.
 *
 * @param {string} source - Raw Turtle string OR path/URL to a .ttl file.
 * @param {HTMLElement|string} container - DOM element or element ID where Sigma renders.
 * @returns {Promise<Sigma>} The initialized Sigma instance.
 */
async function visualizeTurtle(source, container) {
  // 1. Resolve container element
  const containerEl = typeof container === 'string'
    ? document.getElementById(container)
    : container;

  if (!containerEl) {
    throw new Error(`Container element not found: ${container}`);
  }

  // 2. Fetch TTL content if a path/URL is provided instead of raw TTL content
  let ttlData = source;
  if (!source.includes('\n') && (source.endsWith('.ttl') || source.startsWith('./') || source.startsWith('/'))) {
    const response = await fetch(source);
    if (!response.ok) {
      throw new Error(`Failed to load TTL file "${source}": ${response.statusText}`);
    }
    ttlData = await response.text();
  }

  // 3. Parse TTL data using N3.js
  const parser = new N3.Parser();
  const quads = [];

  await new Promise((resolve, reject) => {
    parser.parse(ttlData, (error, quad) => {
      if (error) return reject(error);
      if (quad) quads.push(quad);
      else resolve();
    });
  });

  // 4. Initialize Graphology Graph (Directed Graph)
  const graph = new graphology.Graph({ type: 'directed', multi: true });

  // Helpers for labels and colors
  const getLabel = (value) => {
    if (value.includes('#')) return value.split('#').pop();
    if (value.includes('/')) return value.split('/').pop();
    return value;
  };

  const getColor = (value) => {
    let hash = 0;
    for (let i = 0; i < value.length; i++) {
      hash = value.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 65%, 55%)`;
  };

  // 5. Populate Graphology nodes and edges
  quads.forEach((quad) => {
    const subject = quad.subject.value;
    const predicate = quad.predicate.value;
    const object = quad.object.value;

    if (!graph.hasNode(subject)) {
      graph.addNode(subject, {
        label: getLabel(subject),
        size: 10,
        color: getColor(subject),
        x: Math.random() * 100,
        y: Math.random() * 100
      });
    }

    if (!graph.hasNode(object)) {
      const isLiteral = quad.object.termType === 'Literal';
      graph.addNode(object, {
        label: isLiteral ? `"${object}"` : getLabel(object),
        size: isLiteral ? 6 : 10,
        color: isLiteral ? '#94a3b8' : getColor(object),
        x: Math.random() * 100,
        y: Math.random() * 100
      });
    }

    graph.addEdge(subject, object, {
      label: getLabel(predicate),
      size: 2,
      color: '#cbd5e1'
    });
  });

  // 6. Apply circular layout
  const numNodes = graph.order;
  let index = 0;
  graph.forEachNode((node) => {
    const angle = (2 * Math.PI * index) / numNodes;
    graph.setNodeAttribute(node, 'x', Math.cos(angle) * 100);
    graph.setNodeAttribute(node, 'y', Math.sin(angle) * 100);
    index++;
  });

  // 7. Render with Sigma.js
  const renderer = new Sigma(graph, containerEl, {
    renderEdgeLabels: true,
    defaultEdgeType: 'arrow',
    labelFont: 'sans-serif',
    labelSize: 12,
    edgeLabelSize: 10
  });

  return renderer;
}