import { useEffect, useRef, useState } from 'react'
import { api, fmt, parseData, withBase, type Project } from './api'

type Scene = 'camera' | 'slide' | 'pip' | 'bible' | 'whiteboard' | 'brainstorm' | 'quiz' | 'title'
const SCENES: { id: Scene; label: string; key: string }[] = [
  { id: 'camera', label: 'Câmera', key: '1' }, { id: 'slide', label: 'Slide/PDF', key: '2' },
  { id: 'pip', label: 'Câmera+Slide', key: '3' }, { id: 'bible', label: 'Bíblia', key: '4' },
  { id: 'whiteboard', label: 'Quadro branco', key: '5' }, { id: 'brainstorm', label: 'Brainstorm', key: '6' },
  { id: 'quiz', label: 'Quiz', key: '7' }, { id: 'title', label: 'Abertura', key: '8' },
]
type Stroke = { kind: string; color: string; width: number; points: number[][]; createdAt: number; ttl: number | null; page: number; slot: number }
const idb = (mode: IDBTransactionMode, fn: (s: IDBObjectStore) => void) => new Promise<void>((res, rej) => {
  const r = indexedDB.open('slidecast-studio', 1)
  r.onupgradeneeded = () => r.result.createObjectStore('chunks')
  r.onsuccess = () => { const tx = r.result.transaction('chunks', mode); fn(tx.objectStore('chunks')); tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error) }
  r.onerror = () => rej(r.error)
})

export default function Studio({ project, setProject, flash }: { project: Project | null; setProject: (p: Project) => void; flash: (s: string) => void }) {
  const data = project ? parseData(project) : {}
  const saved = (data.studio || {}) as Record<string, any> // eslint-disable-line
  const canvasRef = useRef<HTMLCanvasElement>(null); const camRef = useRef<HTMLVideoElement>(null)
  const recRef = useRef<MediaRecorder | null>(null); const chunks = useRef<Blob[]>([])
  const startedRef = useRef(0); const pausedMs = useRef(0); const pauseStart = useRef(0)
  const imgCache = useRef<Record<string, HTMLImageElement>>({})
  const [scene, setScene] = useState<Scene>((saved.scene as Scene) || 'slide')
  const [slots, setSlots] = useState<{ title: string; page: number; page_count: number }[]>(
    (saved.pdfs as never[])?.length ? saved.pdfs : [1, 2, 3].map(i => ({ title: `PDF ${i}`, page: 0, page_count: 0 })))
  const [activePdf, setActivePdf] = useState(Number(saved.active_pdf || 1))
  const [pipPos, setPipPos] = useState(saved.pip?.position || 'bottom-right'); const [pipSize, setPipSize] = useState(saved.pip?.size || 'medium'); const [pipOn, setPipOn] = useState(saved.pip?.visible !== false)
  const [tele, setTele] = useState(String(saved.teleprompter?.text || data.script || '')); const [font, setFont] = useState(28); const [speed, setSpeed] = useState(30); const [playing, setPlaying] = useState(false)
  const teleRef = useRef<HTMLDivElement>(null)
  const [bibleRef, setBibleRef] = useState(String(saved.bible?.reference || '')); const [bibleText, setBibleText] = useState(String(saved.bible?.text || '')); const [bibleVersion, setBibleVersion] = useState(String(saved.bible?.version || 'Texto fornecido pela usuária'))
  const [quizQ, setQuizQ] = useState(String(saved.quiz?.question || '')); const [quizOpts, setQuizOpts] = useState<string>((saved.quiz?.options || []).join('\n')); const [quizCorrect, setQuizCorrect] = useState(Number(saved.quiz?.correct || 0)); const [revealed, setRevealed] = useState(false)
  const [cards, setCards] = useState<string>((saved.brainstorm?.cards || []).join('\n')); const [bsTitle, setBsTitle] = useState(String(saved.brainstorm?.title || 'Brainstorm'))
  const [pen, setPen] = useState<'off' | 'temp' | 'perm' | 'highlight'>('off'); const [ttl, setTtl] = useState(5)
  const [strokes, setStrokes] = useState<Stroke[]>((saved.annotations || []).map((s: never) => ({ ...(s as Stroke), createdAt: (s as { created_at: number }).created_at * 1000 })))
  const [board, setBoard] = useState<Stroke[]>([])
  const [recState, setRecState] = useState<'idle' | 'recording' | 'paused' | 'done'>('idle'); const [elapsed, setElapsed] = useState(0); const [level, setLevel] = useState(0)
  const [url, setUrl] = useState(''); const [mp4, setMp4] = useState(''); const [showTimer, setShowTimer] = useState(false); const [quality, setQuality] = useState('1080')
  const drawing = useRef<Stroke | null>(null)
  const stateRef = useRef({ scene, slots, activePdf, pipPos, pipSize, pipOn, strokes, board, bibleRef, bibleText, quizQ, quizOpts, quizCorrect, revealed, cards, bsTitle, showTimer, elapsed })
  stateRef.current = { scene, slots, activePdf, pipPos, pipSize, pipOn, strokes, board, bibleRef, bibleText, quizQ, quizOpts, quizCorrect, revealed, cards, bsTitle, showTimer, elapsed }

  const persist = () => { if (!project) return; const st = { schema_version: 1, scene, pdfs: slots.map((s, i) => ({ slot: i + 1, title: s.title, file: s.page_count ? `studio/pdf${i + 1}.pdf` : null, page: s.page, page_count: s.page_count })), active_pdf: activePdf, pip: { position: pipPos, size: pipSize, visible: pipOn }, teleprompter: { text: tele, font_size: font, speed }, bible: { reference: bibleRef, text: bibleText, version: bibleVersion }, quiz: { question: quizQ, options: quizOpts.split('\n').filter(Boolean), correct: quizCorrect, revealed }, brainstorm: { title: bsTitle, cards: cards.split('\n').filter(Boolean) }, annotations: strokes.map(s => ({ ...s, created_at: s.createdAt / 1000 })) }; api.patchProject(project.id, undefined, { studio: st }, project.revision).then(setProject).catch(e => flash(`Autosave do estúdio: ${String(e)}`)) }

  useEffect(() => { // câmera + microfone com nível real
    let stream: MediaStream; let ac: AudioContext; let raf = 0
    navigator.mediaDevices?.getUserMedia({ video: true, audio: true }).then(s => { stream = s; if (camRef.current) camRef.current.srcObject = s; ac = new AudioContext(); const an = ac.createAnalyser(); ac.createMediaStreamSource(s).connect(an); const buf = new Uint8Array(an.frequencyBinCount); const tick = () => { an.getByteFrequencyData(buf); setLevel(Math.min(1, buf.reduce((a, b) => a + b, 0) / buf.length / 128)); raf = requestAnimationFrame(tick) }; tick() }).catch(() => flash('Câmera/microfone indisponíveis — verifique a permissão do navegador. A gravação de slides continua possível.'))
    return () => { stream?.getTracks().forEach(t => t.stop()); cancelAnimationFrame(raf); ac?.close() }
  }, []) // eslint-disable-line

  useEffect(() => { if (!playing) return; const t = setInterval(() => { if (teleRef.current) teleRef.current.scrollTop += speed / 10 }, 100); return () => clearInterval(t) }, [playing, speed])
  useEffect(() => { if (recState !== 'recording') return; const t = setInterval(() => setElapsed((Date.now() - startedRef.current - pausedMs.current) / 1000), 250); return () => clearInterval(t) }, [recState])
  useEffect(() => { const t = setTimeout(persist, 1200); return () => clearTimeout(t) }, [scene, slots, activePdf, tele, bibleText, quizQ, cards, strokes]) // eslint-disable-line

  useEffect(() => { // palco WYSIWYG: tudo que é desenhado aqui é o que o MediaRecorder captura
    let raf = 0; const draw = () => {
      const c = canvasRef.current, ctx = c?.getContext('2d'); if (!c || !ctx) { raf = requestAnimationFrame(draw); return }
      const S = stateRef.current; const W = c.width, H = c.height; const slot = S.slots[S.activePdf - 1]
      ctx.fillStyle = '#f8fafc'; ctx.fillRect(0, 0, W, H)
      const drawSlide = () => { const key = `${S.activePdf}-${slot?.page}`; let img = imgCache.current[key]; if (!img && project && slot?.page_count) { img = new Image(); img.src = withBase(`/api/projects/${project.id}/studio/pdfs/${S.activePdf}/page/${slot.page}`); imgCache.current[key] = img } if (img?.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, W, H); else { ctx.fillStyle = '#334155'; ctx.font = '36px sans-serif'; ctx.fillText(slot?.page_count ? 'Carregando página…' : 'Envie um PDF em um dos 3 slots abaixo', 60, H / 2) } }
      const drawCam = (x: number, y: number, w: number, h: number) => { const v = camRef.current; if (v?.readyState && v.readyState >= 2) ctx.drawImage(v, x, y, w, h); else { ctx.fillStyle = '#1e293b'; ctx.fillRect(x, y, w, h) } }
      const drawStrokes = (list: Stroke[], forBoard: boolean) => { const now = Date.now(); for (const s of list) { if (!forBoard && (s.slot !== S.activePdf || s.page !== (slot?.page || 0))) continue; if (s.kind === 'temp' && now - s.createdAt > (s.ttl || 5) * 1000) continue; ctx.strokeStyle = s.color; ctx.lineWidth = s.width; ctx.globalAlpha = s.kind === 'highlight' ? 0.35 : 1; ctx.beginPath(); s.points.forEach((p, i) => i ? ctx.lineTo(p[0] * W, p[1] * H) : ctx.moveTo(p[0] * W, p[1] * H)); ctx.stroke(); ctx.globalAlpha = 1 } }
      const text = (t: string, x: number, y: number, size: number, bold = false, color = '#0f172a') => { ctx.fillStyle = color; ctx.font = `${bold ? '700 ' : ''}${size}px sans-serif`; const words = t.split(' '); let line = '', yy = y; for (const w of words) { if (ctx.measureText(line + w).width > W - x * 2) { ctx.fillText(line, x, yy); yy += size * 1.35; line = '' } line += w + ' ' } ctx.fillText(line, x, yy); return yy }
      if (S.scene === 'camera') drawCam(0, 0, W, H)
      else if (S.scene === 'slide') { drawSlide(); drawStrokes(S.strokes, false) }
      else if (S.scene === 'pip') { drawSlide(); drawStrokes(S.strokes, false); if (S.pipOn) { const w = { small: W * 0.18, medium: W * 0.25, large: W * 0.36 }[S.pipSize as 'small'] || W * 0.25; const h = w * 9 / 16; const m = 24; const x = S.pipPos.includes('left') ? m : W - w - m; const y = S.pipPos.includes('top') ? m : H - h - m; ctx.strokeStyle = '#fff'; ctx.lineWidth = 4; ctx.strokeRect(x, y, w, h); drawCam(x, y, w, h) } }
      else if (S.scene === 'bible') { text(S.bibleRef || 'Bíblia', 70, 110, 52, true); text(S.bibleText || 'Cole o versículo ao lado (texto seu ou licenciado) e projete.', 70, 190, 40) }
      else if (S.scene === 'whiteboard') { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H); drawStrokes(S.board, true) }
      else if (S.scene === 'brainstorm') { text(S.bsTitle, 70, 100, 50, true); S.cards.split('\n').filter(Boolean).forEach((card, i) => { const y = 160 + i * 92; ctx.fillStyle = '#e0f2fe'; ctx.fillRect(70, y, W - 140, 72); text(card, 90, y + 48, 32) }) }
      else if (S.scene === 'quiz') { let y = text(S.quizQ || 'Quiz', 70, 110, 48, true); S.quizOpts.split('\n').filter(Boolean).forEach((o, i) => { y += 84; if (S.revealed && i === S.quizCorrect) { ctx.fillStyle = '#dcfce7'; ctx.fillRect(60, y - 52, W - 120, 68) } text(`${i + 1}. ${o}${S.revealed && i === S.quizCorrect ? ' ✓' : ''}`, 80, y, 36) }) }
      else if (S.scene === 'title') { ctx.fillStyle = '#0ea5e9'; ctx.fillRect(0, 0, W, H); text(project?.name || 'SlideCast Studio', 70, H / 2, 64, true, '#fff') }
      if (S.showTimer) { ctx.fillStyle = 'rgba(15,23,42,.85)'; ctx.fillRect(W - 190, 16, 174, 56); text(fmt(S.elapsed), W - 175, 56, 34, true, '#fff') }
      raf = requestAnimationFrame(draw)
    }; raf = requestAnimationFrame(draw); return () => cancelAnimationFrame(raf)
  }, [project]) // eslint-disable-line

  const point = (e: React.PointerEvent) => { const r = canvasRef.current!.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height] }
  const onDown = (e: React.PointerEvent) => { if (scene !== 'whiteboard' && pen === 'off') return; const s: Stroke = { kind: scene === 'whiteboard' ? 'perm' : pen, color: pen === 'highlight' ? '#facc15' : '#e11d48', width: pen === 'highlight' ? 16 : 4, points: [point(e)], createdAt: Date.now(), ttl: pen === 'temp' ? ttl : null, page: slots[activePdf - 1]?.page || 0, slot: activePdf }; drawing.current = s; (scene === 'whiteboard' ? setBoard : setStrokes)(p => [...p, s]) }
  const onMove = (e: React.PointerEvent) => { if (!drawing.current) return; drawing.current.points.push(point(e)); (scene === 'whiteboard' ? setBoard : setStrokes)(p => [...p.slice(0, -1), { ...drawing.current! }]) }
  const uploadPdf = async (slot: number, f: File) => { if (!project) return flash('Abra um projeto primeiro.'); try { const r = await api.studioUploadPdf(project.id, slot, f); const n = [...slots]; n[slot - 1] = { title: r.title, page: 0, page_count: r.page_count }; setSlots(n); setActivePdf(slot); flash(`PDF ${slot} pronto: ${r.page_count} páginas (troca instantânea, página preservada).`) } catch (e) { flash(String(e)) } }
  const goto = (d: number) => { const n = [...slots]; const s = n[activePdf - 1]; if (s) s.page = Math.min(s.page_count - 1, Math.max(0, s.page + d)); setSlots(n) }

  useEffect(() => { const h = (e: KeyboardEvent) => { const tag = (e.target as HTMLElement)?.tagName; if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return; const sc = SCENES.find(s => s.key === e.key); if (sc) setScene(sc.id); if (e.key === 'ArrowRight') goto(1); if (e.key === 'ArrowLeft') goto(-1) }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h) }) // eslint-disable-line

  const startRec = async () => {
    try {
      const canvas = canvasRef.current!; const vs = canvas.captureStream(30)
      let mic: MediaStream | null = null; try { mic = await navigator.mediaDevices.getUserMedia({ audio: true }) } catch { flash('Sem microfone: gravando só o palco. Conecte/autorize o microfone para narrar.') }
      const tracks = [...vs.getVideoTracks(), ...(mic?.getAudioTracks() || [])]
      const mime = ['video/webm;codecs=vp9,opus', 'video/webm', 'video/mp4'].find(m => MediaRecorder.isTypeSupported(m)) || ''
      const rec = new MediaRecorder(new MediaStream(tracks), mime ? { mimeType: mime, videoBitsPerSecond: quality === '1080' ? 8_000_000 : 4_000_000 } : undefined)
      recRef.current = rec; chunks.current = []; await idb('readwrite', s => s.clear()).catch(() => {})
      rec.ondataavailable = e => { if (e.data.size) { const i = chunks.current.length; chunks.current.push(e.data); idb('readwrite', s => s.put(e.data, i)).catch(() => {}) } }
      rec.onstop = () => { setUrl(URL.createObjectURL(new Blob(chunks.current, { type: mime || 'video/webm' }))); setRecState('done') }
      startedRef.current = Date.now(); pausedMs.current = 0; rec.start(2000); setRecState('recording'); flash('Gravando o palco (o teleprompter e os controles NÃO entram no vídeo).')
    } catch (e) { flash(`Não foi possível gravar neste navegador: ${String(e)}`) }
  }
  const pauseRec = () => { const r = recRef.current; if (!r) return; if (r.state === 'recording') { r.pause(); pauseStart.current = Date.now(); setRecState('paused') } else if (r.state === 'paused') { r.resume(); pausedMs.current += Date.now() - pauseStart.current; setRecState('recording') } }
  const convert = async () => { if (!project || !chunks.current.length) return; try { const blob = new Blob(chunks.current, { type: 'video/webm' }); const r = await api.studioConvert(project.id, blob); setMp4(withBase(r.download_url)); flash('MP4 H.264+AAC pronto para baixar.') } catch (e) { flash(String(e)) } }

  if (!project) return <><h1>Estúdio de gravação</h1><p className="err">Abra ou crie um projeto em “Projetos” primeiro — o estúdio salva cenas, PDFs, roteiro e anotações nele.</p></>
  const slot = slots[activePdf - 1]
  return <><h1>Estúdio de gravação — {project.name}</h1>
    <div className="card"><div className="row">{SCENES.map(s => <button key={s.id} className={scene === s.id ? '' : 'sec'} onClick={() => setScene(s.id)}>{s.key} · {s.label}</button>)}</div>
      <canvas ref={canvasRef} width={quality === '1080' ? 1920 : 1280} height={quality === '1080' ? 1080 : 720} style={{ width: '100%', background: '#f8fafc', touchAction: 'none' }} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => { drawing.current = null }} />
      <video ref={camRef} autoPlay muted playsInline style={{ display: 'none' }} />
      <div className="row"><strong>{recState === 'recording' ? '🔴' : recState === 'paused' ? '⏸' : '⚪'} {fmt(elapsed)}</strong><span className="muted">Microfone: {'▮'.repeat(Math.round(level * 10)) || '—'}</span>
        {recState === 'idle' && <button onClick={startRec}>● Gravar</button>}
        {(recState === 'recording' || recState === 'paused') && <><button onClick={pauseRec}>{recState === 'paused' ? '▶ Retomar' : '⏸ Pausar'}</button><button className="danger" onClick={() => { if (confirm('Encerrar a gravação?')) recRef.current?.stop() }}>⏹ Encerrar</button></>}
        <label>Qualidade <select value={quality} onChange={e => setQuality(e.target.value)}><option value="1080">1080p</option><option value="720">720p</option></select></label>
        <label><input type="checkbox" checked={showTimer} onChange={e => setShowTimer(e.target.checked)} /> Mostrar cronômetro no vídeo</label></div>
      {recState === 'done' && <div className="row"><video src={url} controls style={{ maxWidth: 480 }} /><a href={url} download="gravacao.webm">Baixar WebM</a><button onClick={convert}>Converter p/ MP4</button>{mp4 && <a href={mp4}>Baixar MP4</a>}</div>}
      <p className="muted">Trechos são guardados no navegador (IndexedDB) durante a gravação; fechar a aba sem baixar pode perdê-los. Limite honesto: a duração longa depende do espaço do navegador.</p></div>

    <div className="card"><h3>PDFs da aula — até 3, troca instantânea</h3><div className="row">{slots.map((s, i) => <span key={i}><button className={activePdf === i + 1 ? '' : 'sec'} onClick={() => setActivePdf(i + 1)}>{s.title}{s.page_count ? ` · pág. ${s.page + 1}/${s.page_count}` : ''}</button> <label className="sec" style={{ cursor: 'pointer' }}>enviar<input type="file" accept=".pdf" style={{ display: 'none' }} onChange={e => e.target.files?.[0] && uploadPdf(i + 1, e.target.files[0])} /></label></span>)}</div>
      <div className="row"><button className="sec" onClick={() => goto(-1)}>← Anterior</button><span>Página {(slot?.page || 0) + 1} de {slot?.page_count || 0} (setas do teclado também)</span><button className="sec" onClick={() => goto(1)}>Próxima →</button>
      <label>Miniaturas: {slot?.page_count ? Array.from({ length: slot.page_count }, (_, i) => <button key={i} className={slot.page === i ? '' : 'sec'} onClick={() => { const n = [...slots]; n[activePdf - 1].page = i; setSlots(n) }}>{i + 1}</button>) : '—'}</label></div>
      <div className="row"><label>Caneta <select value={pen} onChange={e => setPen(e.target.value as never)}><option value="off">Desligada</option><option value="temp">Temporária (some sozinha)</option><option value="perm">Permanente</option><option value="highlight">Marca-texto</option></select></label>
      {pen === 'temp' && <label>Apagar em <select value={ttl} onChange={e => setTtl(Number(e.target.value))}><option>3</option><option>5</option><option>8</option></select>s</label>}
      <button className="sec" onClick={() => setStrokes(p => p.slice(0, -1))}>Desfazer traço</button><button className="sec" onClick={() => { setStrokes(p => p.filter(s => !(s.slot === activePdf && s.page === slot.page))); setBoard([]) }}>Limpar página/quadro</button>
      <label>Câmera PiP <select value={pipPos} onChange={e => setPipPos(e.target.value)}><option value="bottom-right">Inferior direita</option><option value="bottom-left">Inferior esquerda</option><option value="top-right">Superior direita</option><option value="top-left">Superior esquerda</option></select> <select value={pipSize} onChange={e => setPipSize(e.target.value)}><option value="small">Pequena</option><option value="medium">Média</option><option value="large">Grande</option></select> <label><input type="checkbox" checked={pipOn} onChange={e => setPipOn(e.target.checked)} /> visível</label></label></div>
      <p className="muted">Desenhe sobre o palco com a caneta ativa. A temporária só aparece no vídeo enquanto estiver visível e nunca altera o PDF original.</p></div>

    <div className="card"><h3>Teleprompter (fora da gravação)</h3>
      <div ref={teleRef} style={{ maxHeight: 180, overflowY: 'auto', fontSize: font, lineHeight: 1.5, background: '#fffbeb', padding: 12, whiteSpace: 'pre-wrap' }}>{tele || 'Escreva seu roteiro abaixo…'}</div>
      <textarea rows={4} value={tele} onChange={e => setTele(e.target.value)} placeholder={'Roteiro com marcadores [Slide 1], [Slide 2]…'} />
      <div className="row"><button className="sec" onClick={() => setPlaying(!playing)}>{playing ? 'Pausar rolagem' : 'Rolar'}</button><label>Fonte <input type="range" min={18} max={44} value={font} onChange={e => setFont(Number(e.target.value))} /></label><label>Velocidade <input type="range" min={5} max={80} value={speed} onChange={e => setSpeed(Number(e.target.value))} /></label><span className="muted">Seções: {tele.split(/\[(Slide \d+|Cena:[^\]]+)\]/).filter((_, i) => i % 2 === 1).join(' · ') || '—'}</span></div></div>

    <div className="card"><h3>Bíblia, quadro, brainstorm e quiz</h3>
      <div className="row"><input placeholder="Referência (ex.: João 1:1)" value={bibleRef} onChange={e => setBibleRef(e.target.value)} /><input placeholder="Versão/fonte" value={bibleVersion} onChange={e => setBibleVersion(e.target.value)} /><button className="sec" onClick={() => setScene('bible')}>Projetar versículo</button></div>
      <textarea rows={2} placeholder="Texto do versículo (seu, licenciado ou de domínio público)" value={bibleText} onChange={e => setBibleText(e.target.value)} />
      <div className="row"><input placeholder="Enunciado do quiz" value={quizQ} onChange={e => setQuizQ(e.target.value)} /><button className="sec" onClick={() => setScene('quiz')}>Projetar quiz</button><button className="sec" onClick={() => setRevealed(!revealed)}>{revealed ? 'Ocultar resposta' : 'Revelar resposta'}</button></div>
      <textarea rows={3} placeholder={'Alternativas, uma por linha'} value={quizOpts} onChange={e => setQuizOpts(e.target.value)} />
      <label>Resposta certa (1ª=0) <input type="number" value={quizCorrect} onChange={e => setQuizCorrect(Number(e.target.value))} /></label>
      <div className="row"><input placeholder="Título do brainstorm" value={bsTitle} onChange={e => setBsTitle(e.target.value)} /><button className="sec" onClick={() => setScene('brainstorm')}>Projetar brainstorm</button><button className="sec" onClick={() => setScene('whiteboard')}>Abrir quadro branco</button></div>
      <textarea rows={3} placeholder={'Cards do brainstorm, um por linha'} value={cards} onChange={e => setCards(e.target.value)} /></div>
  </>
}
