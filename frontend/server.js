const express = require('express');
const fs = require('fs');
const path = require('path');
const { Parser } = require('n3');

const app = express();
const PORT = process.env.PORT || 3033;

const CONFIG = {
    ttlFilePath: path.join(__dirname, 'generated_ontology.ttl'),
    jsonFilePath: path.join(__dirname, 'graph.json'),
    rdfTypeUris: [
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
        'http://www.w3.org/2000/01/rdf-schema#subClassOf'
    ],
    labelUris: [
        'http://www.w3.org/2000/01/rdf-schema#label',
        'http://www.w3.org/2004/02/skos/core#prefLabel'
    ],
    commentUris: [
        'http://www.w3.org/2000/01/rdf-schema#comment',
        'http://www.w3.org/2004/02/skos/core#definition'
    ]
};

function getLocalName(uri) {
    if (!uri) return '';
    if (uri.includes('#')) return uri.split('#').pop();
    if (uri.includes('/')) return uri.split('/').pop();
    return uri;
}

// Convert graph.json structure into Sigma/Graphology schema
function loadGraphFromJson(filePath) {
    const rawData = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const connectivity = {};

    const nodes = rawData.entities.map(entity => {
        connectivity[entity.id] = 0;
        return {
            id: entity.id,
            label: entity.label || entity.id,
            type: entity.type || 'Resource',
            description: entity.description || '',
            properties: entity.properties || {},
            canonical_key: entity.canonical_key
        };
    });

    const links = rawData.relationships.map(rel => {
        connectivity[rel.from] = (connectivity[rel.from] || 0) + 1;
        connectivity[rel.to] = (connectivity[rel.to] || 0) + 1;
        return {
            source: rel.from,
            target: rel.to,
            type: rel.type,
            properties: rel.properties || {}
        };
    });

    const analysis = {};
    nodes.forEach(node => {
        analysis[node.id] = {
            connectivity: connectivity[node.id] || 0,
            depth: 1
        };
    });

    return { nodes, links, analysis };
}

// Dynamic parser fallback for raw TTL files
function parseTurtleFile(filePath) {
    return new Promise((resolve, reject) => {
        const ttlData = fs.readFileSync(filePath, 'utf8');
        const parser = new Parser();
        const quads = [];

        parser.parse(ttlData, (error, quad) => {
            if (error) return reject(error);
            if (quad) {
                quads.push(quad);
            } else {
                const nodesMap = new Map();
                const links = [];
                const connectivity = {};

                function ensureNode(id) {
                    if (!nodesMap.has(id)) {
                        nodesMap.set(id, {
                            id: id,
                            label: getLocalName(id),
                            type: 'Resource',
                            description: ''
                        });
                    }
                    return nodesMap.get(id);
                }

                quads.forEach(q => {
                    const subj = q.subject.value;
                    const pred = q.predicate.value;
                    const obj = q.object.value;

                    connectivity[subj] = (connectivity[subj] || 0) + 1;
                    ensureNode(subj);

                    if (q.object.termType === 'NamedNode' || q.object.termType === 'BlankNode') {
                        connectivity[obj] = (connectivity[obj] || 0) + 1;
                        ensureNode(obj);

                        if (CONFIG.rdfTypeUris.includes(pred)) {
                            nodesMap.get(subj).type = getLocalName(obj);
                        } else {
                            links.push({
                                source: subj,
                                target: obj,
                                type: getLocalName(pred)
                            });
                        }
                    } else if (q.object.termType === 'Literal') {
                        const node = nodesMap.get(subj);
                        if (CONFIG.labelUris.includes(pred)) {
                            node.label = obj;
                        } else if (CONFIG.commentUris.includes(pred)) {
                            node.description = obj;
                        } else {
                            node[getLocalName(pred)] = obj;
                        }
                    }
                });

                const analysis = {};
                nodesMap.forEach((node, id) => {
                    analysis[id] = { connectivity: connectivity[id] || 0, depth: 1 };
                });

                resolve({ nodes: Array.from(nodesMap.values()), links, analysis });
            }
        });
    });
}

app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/graph', async (req, res) => {
    try {
        if (fs.existsSync(CONFIG.jsonFilePath)) {
            const graphData = loadGraphFromJson(CONFIG.jsonFilePath);
            return res.json(graphData);
        } else if (fs.existsSync(CONFIG.ttlFilePath)) {
            const graphData = await parseTurtleFile(CONFIG.ttlFilePath);
            return res.json(graphData);
        } else {
            return res.status(404).json({ detail: 'No ontology data source found.' });
        }
    } catch (err) {
        res.status(500).json({ detail: 'Failed to process graph: ' + err.message });
    }
});

app.listen(PORT, () => console.log(`Visualizer running on http://localhost:${PORT}`));