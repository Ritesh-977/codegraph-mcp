import { useEffect, useRef, useState } from 'react'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { buildStyle } from '../graph/style'
import { architecturePositions } from '../graph/layout'
import { startFlow, stopFlow } from '../graph/FlowOverlay'
import { Minimap } from './Minimap'
import { RISK_RAMP } from '../graph/risk'
import type { GraphEdge, GraphNode, Highlight } from '../types'

cytoscape.use(fcose)

export type LayoutName = 'architecture' | 'fcose' | 'concentric' | 'breadthfirst'

export interface GraphCanvasProps {
  elements: ElementDefinition[]
  nodes: GraphNode[]
  edges: GraphEdge[]
  layout: LayoutName
  selectedNodeId: string | null
  riskMode: boolean
  highlight: Highlight | null
  onNodeSelect: (id: string | null) => void
  onNodeHover: (id: string | null) => void
  focusRequest: { id: string; nonce: number } | null
}

const COUPLING_PREFIX = 'coupling:'

export function GraphCanvas(props: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  // Also held in state: mutating a ref never triggers a render, so a minimap
  // gated on `cyRef.current` would never mount.
  const [cyReady, setCyReady] = useState<Core | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props

  useEffect(() => {
    if (!containerRef.current) return
    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: buildStyle(),
      minZoom: 0.03,
      maxZoom: 4,
      wheelSensitivity: 0.25,
    })
    cyRef.current = cy
    setCyReady(cy)

    cy.on('tap', 'node', (evt) => propsRef.current.onNodeSelect(evt.target.id()))
    // Cytoscape has no `tappout`; a tap whose target is the core is background.
    cy.on('tap', (evt) => {
      if (evt.target === cy) propsRef.current.onNodeSelect(null)
    })
    cy.on('mouseover', 'node', (evt) => {
      propsRef.current.onNodeHover(evt.target.id())
      startFlow(cy, evt.target.id())
    })
    cy.on('mouseout', 'node', () => {
      propsRef.current.onNodeHover(null)
      startFlow(cy, null)
    })
    // Labels are zoom-gated, so the stylesheet must be re-evaluated when the
    // zoom crosses the threshold.
    cy.on('zoom', () => cy.style().update())

    return () => {
      cy.destroy()
      cyRef.current = null
      setCyReady(null)
      stopFlow()
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().remove()
    cy.add(props.elements)

    if (props.layout === 'architecture') {
      // `preset` takes a plain id -> {x, y} map; positions are computed rather
      // than simulated, which is the whole point of this view.
      const positions = architecturePositions(props.nodes, props.edges)
      cy.layout({ name: 'preset', positions, fit: true, padding: 60 } as cytoscape.LayoutOptions).run()
      // Layering puts every edge strictly downward, so an edge whose ends share
      // a row can only be part of a cycle. That makes tangles visible without
      // the reader having to ask for them.
      cy.edges().forEach((e) => {
        const a = e.source().data('layer')
        const b = e.target().data('layer')
        if (typeof a === 'number' && a === b) e.addClass('same-layer')
      })
    } else {
      cy.layout({ name: props.layout, animate: false, padding: 50 }).run()
    }
    startFlow(cy, null)
  }, [props.elements, props.nodes, props.edges, props.layout])

  // Selection: neighbourhood highlight with direction colouring.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded in out selected')
    if (!props.selectedNodeId) return
    const ele = cy.$id(props.selectedNodeId)
    if (ele.empty()) return
    ele.addClass('selected')
    const nbr = ele.neighborhood().union(ele)
    cy.elements().not(nbr).addClass('faded')
    ele.outgoers('edge').addClass('out')
    ele.incomers('edge').addClass('in')
  }, [props.selectedNodeId, props.elements])

  // Findings highlight: flag a computed set, and for coupling draw the
  // co-change pairs as extra dotted edges that exist nowhere in the imports.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('flagged flagged-critical')
    cy.edges(`[id ^= "${COUPLING_PREFIX}"]`).remove()
    const h = props.highlight
    if (!h) return
    const cls = h.critical ? 'flagged-critical' : 'flagged'
    for (const id of h.ids) {
      const n = cy.$id(id)
      if (!n.empty()) n.addClass(cls)
    }
    for (const [a, b] of h.pairs ?? []) {
      if (cy.$id(a).empty() || cy.$id(b).empty()) continue
      cy.add({
        data: { id: `${COUPLING_PREFIX}${a}>${b}`, source: a, target: b },
        classes: 'coupling',
      })
    }
  }, [props.highlight, props.elements])

  // Risk overlay: only nodes that actually have history get repainted, so a
  // repo with no clone is visibly "unknown" rather than uniformly safe.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('risk-on')
    if (props.riskMode) cy.nodes().filter((n) => n.data('riskColor') !== undefined).addClass('risk-on')
  }, [props.riskMode, props.elements])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !props.focusRequest) return
    const ele = cy.$id(props.focusRequest.id)
    if (!ele.empty()) {
      cy.animate({ fit: { eles: ele.closedNeighborhood(), padding: 120 }, duration: 280 })
    }
  }, [props.focusRequest])

  return (
    <div className="canvas-wrap">
      <div ref={containerRef} className="cy-host" />
      <canvas className="flow-canvas" id="flow-canvas" />
      {props.layout === 'architecture' && props.elements.length > 0 && (
        <div className="legend">
          <div className="legend__row">
            <span className="legend__dot" style={{ width: 7, height: 7 }} />
            <span className="legend__dot" style={{ width: 13, height: 13 }} />
            <span>size = dependents</span>
          </div>
          {props.riskMode && (
            <div className="legend__row">
              <span className="legend__ramp">
                {RISK_RAMP.map((c) => (
                  <i key={c} style={{ background: c }} />
                ))}
              </span>
              <span>churn x dependents</span>
            </div>
          )}
          <div className="legend__row">
            <span className="legend__swatch" style={{ background: '#3987e5' }} />
            <span>imports (outgoing)</span>
          </div>
          <div className="legend__row">
            <span className="legend__swatch" style={{ background: '#d95926' }} />
            <span>imported by (incoming)</span>
          </div>
          <div className="legend__row">
            <span className="legend__swatch" style={{ background: '#d03b3b' }} />
            <span>same row = circular import</span>
          </div>
          <div className="legend__row">
            <span style={{ color: '#8b96a6' }}>◇</span>
            <span>entry point · top row</span>
          </div>
        </div>
      )}
      {cyReady && <Minimap cy={cyReady} />}
    </div>
  )
}
