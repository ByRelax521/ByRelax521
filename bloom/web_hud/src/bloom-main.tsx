import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import BloomApp from './bloom/BloomApp';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BloomApp />
  </StrictMode>,
);
