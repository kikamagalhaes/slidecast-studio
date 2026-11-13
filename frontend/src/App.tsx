import { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmt, parseData, withBase, type Project } from './api'
import Studio from './Studio'

type View = 'projetos' | 'criar' | 'aula' | 'podcast' | 'tela' | 'materiais' | 'biblioteca' | 'preferencias'
const NAV: { id: View; label: string }[] = [
  { id: 'projetos', label: 'Projetos' }, { id: 'criar', label: 'Criar vídeo' },
  { id: 'aula', label: 'Gravar aula' }, { id: 'podcast', label: 'Podcast' },
  { id: 'tela', label: 'Gravar tela/reunião' }, { id: 'materiais', label: 'Materiais' },
  { id: 'biblioteca', label: 'Biblioteca' }, { id: 'preferencias', label: 'Preferências' },
]

export default function App() {
  const [user, setUser] = useState<{ email: string } | null>(null)
  const [view, setView] = useState<View>('projetos')
  const [projects, setProjects] = useState<Project[]>([])
  const [current, setCurrent] = useState<Project | null>(null)
  const [msg, setMsg] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('slidecast-theme') || 'claro')
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('slidecast-theme', theme) }, [theme])
  const load = useCallback(async () => { try { setProjects((await api.listProjects()).projects) } catch { /* sem sessão */ } }, [])
  useEffect(() => { api.me().then(r => { setUser(r.user); load() }).catch(() => setUser(null)) }, [load])
  if (!user) return <Auth onOk={u => { setUser(u); load() }} />
  const open = async (p: Project) => { setCurrent(await api.getProject(p.id)); setView('criar') }
  return <div className="layout"><aside className="side"><strong>SlideCast Studio</strong><p className="muted">{user.email}</p>
    {NAV.map(n => <button key={n.id} className={view === n.id ? 'on' : ''} onClick={() => setView(n.id)}>{n.label}</button>)}
    <button className="sec" onClick={() => { api.logout(); setUser(null) }}>Sair</button>
    <button className="sec" onClick={() => setTheme(theme === 'escuro' ? 'claro' : 'escuro')}>{theme === 'escuro' ? 'Tema claro' : 'Tema escuro'}</button>{msg && <p className="muted">{msg}</p>}</aside>
    <main className="main">
      {view === 'projetos' && <Projetos projects={projects} reload={load} open={open} setCurrent={setCurrent} setView={setView} flash={setMsg} />}
      {view === 'criar' && <CriarVideo project={current} setProject={setCurrent} reload={load} flash={setMsg} />}
      {view === 'aula' && <Studio project={current} setProject={setCurrent} flash={setMsg} />}
      {view === 'tela' && <Recorder mode="tela" flash={setMsg} reload={load} />}
      {view === 'podcast' && <Podcast flash={setMsg} reload={load} />}
      {view === 'materiais' && <Materiais project={current} flash={setMsg} />}
      {view === 'biblioteca' && <Biblioteca />}
      {view === 'preferencias' && <Preferencias flash={setMsg} />}
    </main></div>
}

function Auth({ onOk }: { onOk: (u: { email: string }) => void }) {
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState('')
  const go = async (reg: boolean) => { try { const r = await (reg ? api.register(email, pw) : api.login(email, pw)) as { user: { email: string } }; onOk(r.user) } catch (e) { setErr(String(e)) } }
  return <main className="main" style={{ maxWidth: 420, margin: '40px auto' }}><div className="card"><h1>SlideCast Studio</h1>
    <p className="muted">Entre para acessar seus projetos. Sem IA: tudo vem dos seus arquivos e textos.</p>
    <p><input placeholder="E-mail" value={email} onChange={e => setEmail(e.target.value)} /></p>
    <p><input placeholder="Senha" type="password" value={pw} onChange={e => setPw(e.target.value)} /></p>
    {err && <p className="err">{err}</p>}<div className="row"><button onClick={() => go(false)}>Entrar</button><button className="sec" onClick={() => go(true)}>Criar conta</button></div></div></main>
}

function Projetos({ projects, reload, open, setCurrent, setView, flash }: { projects: Project[]; reload: () => void; open: (p: Project) => void; setCurrent: (p: Project | null) => void; setView: (v: View) => void; flash: (s: string) => void }) {
  const [name, setName] = useState('')
  const create = async (kind = 'video') => { const p = await api.createProject(name || 'Sem título', kind); flash('Projeto criado.'); setCurrent(p); reload(); setView('criar') }
  return <><h1>Projetos</h1><div className="card"><div className="row"><input style={{ flex: 1 }} placeholder="Nome do novo projeto" value={name} onChange={e => setName(e.target.value)} /><button onClick={() => create()}>Criar projeto</button></div></div>
    {projects.map(p => <div className="card" key={p.id}><div className="row"><strong>{p.name}</strong><span className="muted">{p.kind} · rev {p.revision} · {new Date(p.updated_at).toLocaleString('pt-BR')}</span></div>
      <div className="row"><button onClick={() => open(p)}>Reabrir</button><button className="sec" onClick={async () => { await api.duplicate(p.id); flash('Duplicado.'); reload() }}>Duplicar</button>
      <button className="sec" onClick={async () => { const n = prompt('Novo nome', p.name); if (n) { await api.patchProject(p.id, n, {}, p.revision); reload() } }}>Renomear</button>
      <button className="danger" onClick={async () => { if (confirm('Excluir projeto?')) { await api.remove(p.id); reload() } }}>Excluir</button></div></div>)}
    {!projects.length && <p className="muted">Nenhum projeto ainda.</p>}</>
}

/* Autosave com revisão: conflito 409 vira aviso, nunca sobrescreve em silêncio. */
function useAutosave(project: Project | null, setProject: (p: Project) => void, flash: (s: string) => void) {
  const timer = useRef<number | undefined>(undefined)
  return useCallback((data: Record<string, unknown>, name?: string) => {
    if (!project) return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      try { setProject(await api.patchProject(project.id, name, data, project.revision)); flash('Salvo automaticamente.') }
      catch (e) { flash(`Autosave: ${String(e)} — recarregue o projeto.`) }
    }, 800)
  }, [project, setProject, flash])
}

function CriarVideo({ project, setProject, reload, flash }: { project: Project | null; setProject: (p: Project) => void; reload: () => void; flash: (s: string) => void }) {
  const data = project ? parseData(project) : {}
  const save = useAutosave(project, setProject, flash)
  const [pdf, setPdf] = useState<File | null>(null); const [audio, setAudio] = useState<File | null>(null)
  const [slides, setSlides] = useState<{ index: number; thumbnail_url: string; duration: number }[]>([])
  const [durations, setDurations] = useState<number[]>([]); const [locked, setLocked] = useState<Record<string, number>>({})
  const [mode, setMode] = useState('uniforme'); const [script, setScript] = useState(String(data.script || ''))
  const [jobId, setJobId] = useState(''); const [job, setJob] = useState<{ status_pt: string; progress: number; download_url: string | null } | null>(null)
  const [subs, setSubs] = useState(''); const [marks, setMarks] = useState<number[]>([])
  const audioRef = useRef<HTMLAudioElement>(null)
  useEffect(() => { if (data.timings) setDurations(data.timings as number[]) }, [project?.id]) // eslint-disable-line
  const upload = async () => { if (!pdf || !audio) return flash('Selecione PDF e áudio.'); const r = await api.upload(pdf, audio); setSlides(r.slides); setDurations(r.slides.map(s => s.duration)); flash(`Enviado: ${r.page_count} slides, áudio ${fmt(r.audio_duration)}.`); reload() }
  const timings = async () => { if (!project) return flash('Crie/abra um projeto primeiro (Projetos).'); try { const total = Number(data.audio_duration || durations.reduce((a, b) => a + b, 0) || 60); const r = await api.timings(project.id, mode === 'roteiro' || mode === 'travas' ? 'roteiro' : 'uniforme', total, script, locked); setDurations(r.durations); flash(mode === 'roteiro' ? 'Estimativa pelo roteiro aplicada.' : 'Durações aplicadas.') } catch (e) { flash(String(e)) } }
  useEffect(() => { if (!jobId) return; const t = setInterval(async () => { const j = await api.job(jobId); setJob(j); if (['concluido', 'falhou', 'cancelado'].includes(j.status_pt)) clearInterval(t) }, 1500); return () => clearInterval(t) }, [jobId])
  const exportar = async () => { if (!project) return; const r = await api.render(project.id, durations); setJobId(r.job_id); flash('Exportação iniciada.') }
  return <><h1>Criar vídeo</h1>
    {!project && <p className="err">Nenhum projeto aberto — crie um em Projetos. O envio abaixo cria o projeto de vídeo.</p>}
    <div className="card"><h3>PDF + áudio</h3><div className="row"><label>PDF <input type="file" accept=".pdf" onChange={e => setPdf(e.target.files?.[0] || null)} /></label><label>Áudio <input type="file" accept="audio/*,.webm" onChange={e => setAudio(e.target.files?.[0] || null)} /></label><button onClick={upload}>Enviar</button></div>
    {!!slides.length && <div className="grid">{slides.map(s => <figure key={s.index}><img className="thumb" src={withBase(s.thumbnail_url)} alt={`Slide ${s.index + 1}`} /><figcaption className="muted">Slide {s.index + 1} · {fmt(durations[s.index] || s.duration)}</figcaption></figure>)}</div>}</div>
    <div className="card"><h3>Duração dos slides — 5 formas</h3>
      <select value={mode} onChange={e => setMode(e.target.value)}><option value="uniforme">1 · Divisão uniforme</option><option value="roteiro">2 · Estimativa pelo roteiro</option><option value="manual">3 · Manual (editar números abaixo)</option><option value="travas">4 · Travas + Estimativa pelo roteiro</option><option value="marcar">5 · Ouvir e marcar trocas</option></select>
      <p className="muted">“Estimativa pelo roteiro” e “Sugestão por pausas” são estimativas pelo texto/tempo — o sistema não transcreveu nem compreendeu o áudio.</p>
      <textarea rows={5} placeholder="Roteiro com [Slide 1], [Slide 2]…" value={script} onChange={e => { setScript(e.target.value); save({ script: e.target.value }) }} />
      {mode === 'marcar' && <><audio ref={audioRef} controls src={audio ? URL.createObjectURL(audio) : undefined} /><button className="sec" onClick={() => { if (audioRef.current) setMarks([...marks, Math.round(audioRef.current.currentTime * 10) / 10]) }}>Marcar troca agora</button><span className="muted">Marcas: {marks.join('s, ') || '—'}</span></>}
      <div className="row">{durations.map((d, i) => <label key={i}>S{i + 1} <input type="number" step="0.1" value={d} onChange={e => { const n = [...durations]; n[i] = Number(e.target.value); setDurations(n) }} /><input type="checkbox" checked={i in locked} onChange={e => { const l = { ...locked }; if (e.target.checked) l[String(i)] = durations[i]; else delete l[String(i)]; setLocked(l) }} /> travar</label>)}</div>
      <button onClick={timings}>Aplicar duração</button></div>
    <div className="card"><h3>Abertura, encerramento, música, legenda e identidade</h3>
      {(['abertura', 'encerramento', 'musica', 'identidade'] as const).map(k => <p key={k}><label>{k} <input defaultValue={String(data[k] || '')} onChange={e => save({ [k]: e.target.value })} /></label></p>)}
      <p className="muted">Apresentador: vídeo gravado, imagem estática ou “Animação por ritmo” (movimento por pausas do áudio, sem IA).</p>
      <label>Legendas SRT/VTT do usuário <textarea rows={6} value={subs} onChange={e => setSubs(e.target.value)} /></label>
      <div className="row"><button className="sec" onClick={async () => { if (project) { await api.putSubtitles(project.id, subs, subs.trim().startsWith('WEBVTT') ? 'vtt' : 'srt'); flash('Legendas salvas.') } }}>Salvar legendas</button>
      {project && <a href={withBase(`/api/projects/${project.id}/subtitles/export?format=srt`)}>Exportar SRT</a>}{project && <a href={withBase(`/api/projects/${project.id}/subtitles/export?format=vtt`)}>Exportar VTT</a>}</div>
      {!!subs && <p className="muted">Prévia da legenda sobre o áudio: {subs.split('\n').filter(l => l && !l.includes('-->') && isNaN(Number(l)))[0] || ''}</p>}</div>
    <div className="card"><h3>Exportar</h3><div className="row"><button onClick={exportar}>Exportar vídeo</button>{jobId && <button className="sec" onClick={async () => { await api.cancelJob(jobId); flash('Cancelamento solicitado.') }}>Cancelar</button>}{jobId && <button className="sec" onClick={exportar}>Repetir</button>}{job?.download_url && <a href={withBase(job.download_url)}>Baixar vídeo</a>}</div>
    {job && <p>Status real: <strong>{job.status_pt}</strong> · {Math.round(job.progress)}%</p>}</div></>
}

function Recorder({ mode, flash, reload }: { mode: 'aula' | 'tela'; flash: (s: string) => void; reload: () => void }) {
  const mainRef = useRef<HTMLVideoElement>(null); const camRef = useRef<HTMLVideoElement>(null)
  const recRef = useRef<MediaRecorder | null>(null); const chunks = useRef<Blob[]>([])
  const [tele, setTele] = useState(''); const [list, setList] = useState<number[]>([]); const [url, setUrl] = useState('')
  const start = async () => {
    try {
      const main = mode === 'tela' ? await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true }) : await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      if (mainRef.current) mainRef.current.srcObject = main
      main.getVideoTracks()[0]?.addEventListener('ended', () => flash('Compartilhamento encerrado pelo usuário/sistema.'))
      try { const cam = await navigator.mediaDevices.getUserMedia({ video: true }); if (camRef.current) camRef.current.srcObject = cam } catch { flash('Câmera sobreposta indisponível (permissão negada).') }
      const mime = ['video/webm;codecs=vp9', 'video/webm', 'video/mp4'].find(m => MediaRecorder.isTypeSupported(m)) || ''
      const rec = new MediaRecorder(main, mime ? { mimeType: mime } : undefined); recRef.current = rec; chunks.current = []
      rec.ondataavailable = e => { if (e.data.size) { chunks.current.push(e.data); setList(chunks.current.map(c => c.size)) } }
      rec.onstop = () => setUrl(URL.createObjectURL(new Blob(chunks.current, { type: mime || 'video/webm' })))
      rec.start(2000); flash('Gravando — trechos chegando a cada 2s (envio incremental nesta sessão).')
    } catch { flash('Permissão negada ou dispositivo indisponível.') }
  }
  const stop = async () => { recRef.current?.stop(); const p = await api.createProject(mode === 'aula' ? 'Aula gravada' : 'Tela/reunião gravada', mode === 'aula' ? 'aula' : 'tela', { trechos: list.length, teleprompter: tele }); flash(`Projeto criado: ${p.name}. Baixe o vídeo ao lado para guardar o arquivo.`); reload() }
  return <><h1>{mode === 'aula' ? 'Gravar aula' : 'Gravar tela/reunião'}</h1><div className="card"><div className="wrap"><video ref={mainRef} autoPlay muted playsInline /><video ref={camRef} className="cam" autoPlay muted playsInline /></div>
    <textarea rows={4} placeholder="Teleprompter manual — seu texto, role você mesmo" value={tele} onChange={e => setTele(e.target.value)} />
    <div className="row"><button onClick={start}>Iniciar gravação</button><button className="sec" onClick={stop}>Parar e criar projeto</button>{url && <a href={url} download="gravacao.webm">Baixar gravação</a>}</div>
    <p className="muted">Trechos recebidos: {list.length} ({list.reduce((a, b) => a + b, 0)} bytes). Ata/resumo: preencha em Materiais — nada é gerado automaticamente.</p></div></>
}

function Podcast({ flash, reload }: { flash: (s: string) => void; reload: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null); const [fade, setFade] = useState(1); const [norm, setNorm] = useState(false); const [duck, setDuck] = useState(0)
  const wave = async (f: File) => { const buf = await new AudioContext().decodeAudioData(await f.arrayBuffer()); const ch = buf.getChannelData(0); const c = canvas.current!; const ctx = c.getContext('2d')!; ctx.clearRect(0, 0, c.width, c.height); ctx.fillStyle = '#8ab4f8'; for (let x = 0; x < c.width; x++) { const v = Math.abs(ch[Math.floor(x / c.width * ch.length)] || 0); ctx.fillRect(x, (1 - v) * 40, 1, v * 80) } flash(`Onda real desenhada de ${f.name} (${fmt(buf.duration)}).`) ; await api.createProject(`Podcast — ${f.name}`, 'podcast', { fade, normalizacao: norm, ducking: duck }); reload() }
  // Capa final: capas prontas ou imagem enviada + título/assinatura com cores
  const [covers, setCovers] = useState<{ id: string; name: string; url: string; palette: { bg: string; mic: string; accent: string } }[]>([])
  const [coverFormat, setCoverFormat] = useState('quadrada')
  const [presetBg, setPresetBg] = useState('#10151f'); const [presetMic, setPresetMic] = useState('#e8eef4'); const [presetAccent, setPresetAccent] = useState('#f0b35c')
  const [presetId, setPresetId] = useState(''); const [coverFile, setCoverFile] = useState<File | null>(null)
  const [epTitle, setEpTitle] = useState(''); const [epAuthor, setEpAuthor] = useState('')
  const [titleColor, setTitleColor] = useState('#ffffff'); const [titleOutline, setTitleOutline] = useState('#000000')
  const [authorColor, setAuthorColor] = useState('#f2d492'); const [authorOutline, setAuthorOutline] = useState('#000000')
  const [finalUrl, setFinalUrl] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { api.podcastCovers().then(r => setCovers(r.covers)).catch(() => setCovers([])) }, [])
  const baseUrl = coverFile ? URL.createObjectURL(coverFile) : (covers.find(c => c.id === presetId)?.url ? withBase(covers.find(c => c.id === presetId)!.url) : '')
  const gerarCapa = async () => {
    if (!coverFile && !presetId) return flash('Escolha uma capa pronta ou envie uma imagem primeiro.')
    setBusy(true)
    try { const blob = await api.composePodcastCover({ image: coverFile, presetId, title: epTitle, author: epAuthor, titleColor, titleOutlineColor: titleOutline, authorColor, authorOutlineColor: authorOutline, coverFormat, presetBg: !coverFile && presetId ? presetBg : undefined, presetMic: !coverFile && presetId ? presetMic : undefined, presetAccent: !coverFile && presetId ? presetAccent : undefined }); setFinalUrl(URL.createObjectURL(blob)); flash('Capa final gerada: título e assinatura já estão na imagem.') }
    catch (e) { flash(String(e)) } finally { setBusy(false) }
  }
  const cor = (label: string, v: string, set: (s: string) => void) => <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '.9em' }}>{label}<span style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="color" value={v} onChange={e => set(e.target.value)} style={{ width: 52, height: 34, padding: 2 }} /><span className="muted">{v}</span></span></label>
  return <><h1>Podcast</h1>
    <div className="card"><h3>Capa do podcast</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 300px) 1fr', gap: 18, alignItems: 'start' }}>
        <div>
          {(finalUrl || baseUrl) ? <img src={finalUrl || baseUrl} alt="Capa do podcast" style={{ width: '100%', aspectRatio: coverFormat === 'widescreen' ? '16/9' : '1', objectFit: 'cover', borderRadius: 10, border: '1px solid #e2e8f0' }} /> : <div style={{ width: '100%', aspectRatio: coverFormat === 'widescreen' ? '16/9' : '1', border: '1.5px dashed #cbd5e1', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 12 }} className="muted">Escolha uma capa pronta ou envie uma imagem</div>}
          {finalUrl && <p><a href={finalUrl} download="capa-podcast.png"><button type="button">Baixar capa final (PNG)</button></a></p>}
        </div>
        <div>
          <p className="muted" style={{ marginTop: 0 }}>Capas prontas (quadradas, prontas para usar):</p>
          <div className="row">{covers.map(c => <button key={c.id} type="button" className="sec" onClick={() => { setPresetId(c.id); setCoverFile(null); setFinalUrl(''); setPresetBg(c.palette.bg); setPresetMic(c.palette.mic); setPresetAccent(c.palette.accent) }} style={presetId === c.id && !coverFile ? { outline: '3px solid #2563eb', padding: 4 } : { padding: 4 }}><img src={withBase(c.url)} alt={c.name} style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6, display: 'block' }} /><span style={{ fontSize: '.8em' }}>{c.name}</span></button>)}</div>
          <p><label>Ou envie a sua imagem de capa <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { setCoverFile(e.target.files?.[0] || null); setFinalUrl('') }} /></label></p>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10 }}>
            <label>Título do episódio<input placeholder="Ex.: Por que a Nova Jerusalém tem formato de cubo?" value={epTitle} onChange={e => setEpTitle(e.target.value)} /></label>
            <label>Quem apresenta (assinatura)<input placeholder="Ex.: Kika Magalhães" value={epAuthor} onChange={e => setEpAuthor(e.target.value)} /></label>
          </div>
          <div className="row" style={{ marginTop: 10 }}><label>Formato da capa final <select value={coverFormat} onChange={e => setCoverFormat(e.target.value)}><option value="quadrada">Quadrada 1:1 (1080×1080)</option><option value="widescreen">Retangular Widescreen 16:9 (1920×1080)</option></select></label></div>
          <p className="muted" style={{ marginBottom: 4 }}>Cores do desenho da capa pronta (fundo, microfone e ondas):</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(110px, 1fr))', gap: 10 }}>
            {cor('Fundo da capa', presetBg, setPresetBg)}{cor('Microfone e PODCAST', presetMic, setPresetMic)}{cor('Ondas e moldura', presetAccent, setPresetAccent)}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(110px, 1fr))', gap: 10, marginTop: 10 }}>
            {cor('Cor do título', titleColor, setTitleColor)}{cor('Contorno do título', titleOutline, setTitleOutline)}{cor('Cor da assinatura', authorColor, setAuthorColor)}{cor('Contorno da assinatura', authorOutline, setAuthorOutline)}
          </div>
          <p><button onClick={gerarCapa} disabled={busy}>{busy ? 'Gerando…' : 'Gerar capa final'}</button></p>
          <p className="muted">O título e o nome são gravados sobre a capa escolhida — pronta ou enviada — e a imagem final sai no formato escolhido (1080×1080 ou 1920×1080).</p>
        </div>
      </div>
    </div>
    <div className="card"><h3>Áudio do episódio</h3><input type="file" accept="audio/*" onChange={e => e.target.files?.[0] && wave(e.target.files[0])} /><canvas ref={canvas} width={800} height={90} />
    <p className="muted">Processamento de sinal (não é IA): ajustes apenas salvos no projeto — a exportação de podcast ainda não os aplica (sem export de podcast nesta versão).</p>
    <label>Fade (s) <input type="number" step="0.5" value={fade} onChange={e => setFade(Number(e.target.value))} /></label>
    <label><input type="checkbox" checked={norm} onChange={e => setNorm(e.target.checked)} /> Normalização</label>
    <label>Ducking da música (dB) <input type="number" value={duck} onChange={e => setDuck(Number(e.target.value))} /></label></div></>
}

function Materiais({ project, flash }: { project: Project | null; flash: (s: string) => void }) {
  const save = useAutosave(project, () => {}, flash); const [f, setF] = useState<Record<string, string>>({})
  const set = (k: string, v: string) => { setF({ ...f, [k]: v }); save({ materiais: { ...f, [k]: v } }) }
  return <><h1>Materiais</h1><p className="muted">Capas, slides, apostila e ata usam <strong>só o conteúdo que você escrever</strong>. Campo vazio continua vazio.</p>
    {!project && <p className="err">Abra um projeto em Projetos primeiro.</p>}
    {([['capa', 'Capa (título)'], ['slidesExtras', 'Slides por modelo (texto)'], ['apostila', 'Apostila (seu texto)'], ['ata', 'Ata (participantes, decisões, tarefas)']] as const).map(([k, label]) => <div className="card" key={k}><label>{label}<textarea rows={5} value={f[k] || ''} onChange={e => set(k, e.target.value)} /></label></div>)}</>
}

function Biblioteca() {
  const [jobs, setJobs] = useState<Record<string, unknown>[]>([]); const [exps, setExps] = useState<Record<string, unknown>[]>([])
  useEffect(() => { api.jobs().then(r => setJobs(r.jobs)); api.exports().then(r => setExps(r.exports)) }, [])
  return <><h1>Biblioteca</h1><div className="card"><h3>Exportações e jobs (histórico durável)</h3>{jobs.map(j => <p key={String(j.id)}>{String(j.status)} · {String(j.kind)} · {String(j.created_at)}</p>)}{!jobs.length && <p className="muted">Nada ainda.</p>}{exps.map(e => <p key={String(e.id)}>Export {String(e.format)} · {String(e.created_at)}</p>)}</div></>
}

function Preferencias({ flash }: { flash: (s: string) => void }) {
  const [prefs, setPrefs] = useState<Record<string, unknown>>({}); const [k, setK] = useState('resolucao'); const [v, setV] = useState('')
  useEffect(() => { api.prefs().then(setPrefs) }, [])
  return <><h1>Preferências</h1><div className="card"><pre>{JSON.stringify(prefs, null, 2)}</pre><div className="row"><input placeholder="Chave" value={k} onChange={e => setK(e.target.value)} /><input placeholder="Valor" value={v} onChange={e => setV(e.target.value)} /><button onClick={async () => { await api.putPref(k, v); setPrefs(await api.prefs()); flash('Preferência salva.') }}>Salvar</button></div></div></>
}
