import type { NodeSingular, StylesheetJson } from 'cytoscape'

const LABEL_MIN_ZOOM = 0.9

// Zoom-gated: at 5k nodes, drawing every label is what kills the frame rate.
export const LABEL_FN = (ele: NodeSingular): string => {
  const z = typeof ele.cy === 'function' ? ele.cy().zoom() : 1
  return z >= LABEL_MIN_ZOOM ? (ele.data('label') as string) : ''
}

// Selectors key off the `node-<kind>` / `edge-<TYPE>` classes emitted by
// graph/toCytoscape.ts — keep the two in step.
export const buildStyle = (): StylesheetJson => [
  {
    selector: 'node',
    style: {
      width: 18,
      height: 18,
      'background-color': 'data(color)',
      label: LABEL_FN,
      'font-size': 11,
      'text-valign': 'bottom',
      'text-margin-y': 6,
      color: '#d8d8d8',
      'overlay-opacity': 0.15,
    },
  },
  {
    selector: 'node.node-symbol',
    style: { shape: 'rectangle', width: 26, height: 14, label: 'data(label)' },
  },
  {
    selector: 'node.node-dir_cluster',
    style: {
      shape: 'round-rectangle',
      width: 34,
      height: 22,
      'border-width': 2,
      'border-color': 'data(color)',
      'background-color': '#232a36',
      label: 'data(label)',
    },
  },
  {
    selector: 'node.selected',
    style: { 'border-width': 3, 'border-color': '#ffffff' },
  },
  {
    selector: 'node.faded, edge.faded',
    style: { opacity: 0.08 },
  },
  {
    selector: 'edge',
    style: {
      width: 1.5,
      'line-color': '#5a6572',
      'target-arrow-color': '#5a6572',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.1,
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge.edge-IMPORTS',
    style: { 'line-color': '#4e7fa5', 'target-arrow-color': '#4e7fa5' },
  },
  {
    selector: 'edge.out',
    style: { 'line-color': '#3f7ef7', 'target-arrow-color': '#3f7ef7', width: 2.4 },
  },
  {
    selector: 'edge.in',
    style: { 'line-color': '#ef5350', 'target-arrow-color': '#ef5350', width: 2.4 },
  },
]
