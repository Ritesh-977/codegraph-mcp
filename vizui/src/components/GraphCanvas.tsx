import { useEffect, useRef, useState } from 'react'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { buildStyle } from '../graph/style'
import { startFlow, stopFlow } from '../graph/FlowOverlay'
import { Minimap } from './Minimap'

cytoscape.use(fcose)

export interface GraphCanvasProps {
  elements: ElementDefinition[]
  layout: 'fcose' | 'concentric' | 'breadthfirst'
  selectedNodeId: string | null
  onNodeSelect: (id: string | null) => void
  onNodeHover: (id: string | null) => void
  focusRequest: { id: string; nonce: number } | null
}

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
      layout: { name: 'fcose' },
      minZoom: 0.04,
      maxZoom: 4,
      wheelSensitivity: 0.25,
    })
    cyRef.current = cy
    setCyReady(cy)

    cy.on('tap', 'node', (evt) => {
      propsRef.current.onNodeSelect(evt.target.id())
    })
    // Cytoscape has no `tappout`; a tap whose target is the core itself is the
    // background click.
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
    // Labels are zoom-gated, so the stylesheet has to be re-evaluated when the
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
    cy.layout({ name: props.layout, animate: false }).run()
    startFlow(cy, null)
  }, [props.elements, props.layout])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded in out selected')
    if (props.selectedNodeId) {
      const ele = cy.$id(props.selectedNodeId)
      if (!ele.empty()) {
        ele.addClass('selected')
        const nbr = ele.neighborhood().union(ele)
        cy.elements().not(nbr).addClass('faded')
        ele.outgoers('edge').addClass('out')
        ele.incomers('edge').addClass('in')
      }
    }
  }, [props.selectedNodeId, props.elements])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !props.focusRequest) return
    const ele = cy.$id(props.focusRequest.id)
    if (!ele.empty()) {
      cy.animate({ fit: { eles: ele, padding: 60 }, duration: 250 })
    }
  }, [props.focusRequest])

  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
      <canvas
        id="flow-canvas"
        style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 5 }}
      />
      {cyReady && <Minimap cy={cyReady} />}
    </div>
  )
}
