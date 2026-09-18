import type { NodeSingular, StylesheetJson } from 'cytoscape'

const LABEL_MIN_ZOOM = 0.62

// Zoom-gated: at a few thousand nodes, drawing every label is what kills the
// frame rate — and an unreadable wall of text helps nobody anyway.
export const LABEL_FN = (ele: NodeSingular): string => {
  const z = typeof ele.cy === 'function' ? ele.cy().zoom() : 1
  if (z >= LABEL_MIN_ZOOM) return ele.data('label') as string
  // Above the threshold only the load-bearing files keep their names.
  return (ele.data('fanIn') as number) >= 8 ? (ele.data('label') as string) : ''
}

/**
 * The canvas is deliberately quiet. Size carries importance (dependents) and
 * position carries dependency depth; colour is held in reserve for the two
 * things worth shouting about — edge direction on selection, and whichever
 * finding the reader has chosen to highlight. A graph where everything is
 * coloured is a graph where nothing stands out.
 *
 * Selectors key off the `node-<kind>` / `edge-<TYPE>` classes emitted by
 * graph/toCytoscape.ts — keep the two in step.
 */
export const buildStyle = (): StylesheetJson => [
  {
    selector: 'node',
    style: {
      width: 'data(size)',
      height: 'data(size)',
      'background-color': '#3d4654',
      'border-width': 1.5,
      'border-color': '#5b6674',
      label: LABEL_FN,
      'font-family': 'ui-monospace, SFMono-Regular, Menlo, monospace',
      'font-size': 10,
      'text-valign': 'bottom',
      'text-margin-y': 5,
      'text-max-width': '120px',
      color: '#a2a9b6',
      'text-background-color': '#14171c',
      'text-background-opacity': 0.75,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
      'overlay-opacity': 0,
      'transition-property': 'background-color, border-color, opacity, width, height',
      'transition-duration': 140,
    },
  },
  {
    // Entry points are where a reader starts; give them presence without colour.
    selector: 'node.is-entry',
    style: { 'border-width': 2, 'border-color': '#8b96a6', shape: 'round-diamond' },
  },
  {
    selector: 'node.node-symbol',
    style: {
      shape: 'round-rectangle',
      width: 10,
      height: 10,
      'background-color': '#2a313c',
      'border-color': '#414b59',
      'border-style': 'dashed',
      color: '#6d7686',
    },
  },
  {
    selector: 'node.node-dir_cluster',
    style: {
      shape: 'round-rectangle',
      'background-color': '#232a35',
      'border-width': 2,
      'border-color': '#4d5869',
      label: 'data(label)',
      'font-size': 12,
      color: '#e8eaee',
      'text-valign': 'center',
      'text-margin-y': 0,
    },
  },
  {
    selector: 'node.selected',
    style: {
      'background-color': '#5a687c',
      'border-width': 2.5,
      'border-color': '#e8eaee',
      color: '#e8eaee',
      label: 'data(label)',
      'z-index': 30,
    },
  },
  {
    // A highlighted finding set — only ever one finding at a time, so this
    // colour never has to compete with the edge-direction pair.
    selector: 'node.flagged',
    style: {
      'background-color': '#199e70',
      'border-color': '#3fd39c',
      'border-width': 2.5,
      label: 'data(label)',
      color: '#cdeee0',
      'z-index': 25,
    },
  },
  {
    selector: 'node.flagged-critical',
    style: {
      'background-color': '#d03b3b',
      'border-color': '#f08b8b',
      'border-width': 2.5,
      label: 'data(label)',
      color: '#ffd7d7',
      'z-index': 25,
    },
  },
  {
    // Risk overlay. Sequential magnitude encoding, so it replaces the node's
    // resting colour rather than adding another hue to the picture.
    selector: 'node.risk-on',
    style: { 'background-color': 'data(riskColor)', 'border-color': 'data(riskColor)' },
  },
  { selector: '.faded', style: { opacity: 0.1 } },
  {
    selector: 'edge',
    style: {
      width: 1,
      'line-color': '#333b47',
      'target-arrow-color': '#3d4654',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.75,
      'curve-style': 'bezier',
      'transition-property': 'line-color, target-arrow-color, width, opacity',
      'transition-duration': 140,
    },
  },
  {
    // Longest-path layering guarantees every edge points strictly downward —
    // EXCEPT inside a cycle, whose members all share a row. So a level edge is
    // exactly a circular dependency, and worth calling out on sight.
    selector: 'edge.same-layer',
    style: {
      'line-color': '#d03b3b',
      'target-arrow-color': '#d03b3b',
      'line-style': 'dashed',
      width: 2,
      'z-index': 21,
    },
  },
  {
    selector: 'edge.out',
    style: { 'line-color': '#3987e5', 'target-arrow-color': '#3987e5', width: 2, 'z-index': 20 },
  },
  {
    selector: 'edge.in',
    style: { 'line-color': '#d95926', 'target-arrow-color': '#d95926', width: 2, 'z-index': 20 },
  },
  {
    selector: 'edge.coupling',
    style: {
      'line-color': '#fab219',
      'line-style': 'dotted',
      width: 2,
      'target-arrow-shape': 'none',
      'z-index': 22,
    },
  },
]
