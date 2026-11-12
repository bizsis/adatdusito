import React from 'react';
import {createRoot} from 'react-dom/client';
function App() {
  const [status, setStatus] = React.useState('Ellenőrzés…');
  React.useEffect(() => { fetch('/api/health/ready').then(r => setStatus(r.ok ? 'A fejlesztői szolgáltatások elérhetők.' : 'Egy vagy több szolgáltatás még nem áll készen.')).catch(() => setStatus('A backend nem érhető el.')); }, []);
  return <main><h1>Adatdúsító</h1><p>Fejlesztői környezet – infrastruktúra</p><p role="status">{status}</p></main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
