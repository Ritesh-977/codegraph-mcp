// cytoscape-fcose ships no type declarations; it is only ever handed to
// `cytoscape.use()`, so the extension needs no surface beyond that.
declare module 'cytoscape-fcose' {
  import type { Ext } from 'cytoscape'
  const ext: Ext
  export default ext
}
