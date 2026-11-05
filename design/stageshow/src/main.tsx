import React from 'react'
import { createRoot } from 'react-dom/client'
import PolicyPreview from './PolicyPreview'
import './page.css'

const isGold = new URLSearchParams(location.search).has('gold')
if (isGold) {
  import('../reference').then(({ default: Gold }) => {
    createRoot(document.getElementById('root')!).render(<React.StrictMode><main><Gold /></main></React.StrictMode>)
  })
} else {
  createRoot(document.getElementById('root')!).render(<React.StrictMode><main><PolicyPreview /></main></React.StrictMode>)
}
