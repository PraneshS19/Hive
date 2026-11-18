import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './design-tokens.css';
import './styles.css';
import './silk.css';
import './silkv2.css';
import './home-background.css';
import './homepage-motion.css';
import './immersive.css';
import './layout-refinement.css';
import './reasoned-scroll.css';
import './layout-recovery.css';
import './alignment-flow.css';
import './dock-nav.css';
import './design-system.css';
import './text-roll.css';
import './datasets.css';
import './review.css';
import './neumorphic.css';
import { GlowingEffect } from './components/ui/glowing-effect';
import App from './App';
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GlowingEffect />
    <App />
  </StrictMode>
);
