import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import PitchDeck from './PitchDeck.jsx'
import Landing from './Landing.jsx'

const params = new URLSearchParams(window.location.search)
const deck = params.get('deck') || window.location.hash.replace('#', '')

let Root = Landing
if (deck === 'pitch') Root = PitchDeck
else if (deck === 'demo' || deck === 'demoday') Root = App

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
