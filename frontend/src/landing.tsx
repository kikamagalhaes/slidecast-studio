import React from 'react'
import { createRoot } from 'react-dom/client'
import productImage from './assets/desktop-editor.png'
import studioImage from './assets/desktop-studio.png'
import release from '../landing/public/releases.json'
import './landing.css'

const downloadsReady = release.status === 'published'
const windows = release.platforms.windows
const linux = release.platforms.linux
const sizeLabel = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
const Arrow = () => <span aria-hidden="true">↗</span>
function Brand() {
  return <a className="brand" href="#inicio" aria-label="SlideCast Studio, início"><svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true"><rect x="2" y="3" width="22" height="26" rx="5" fill="currentColor"/><path d="m12 10 9 6-9 6z" fill="#f3eee2"/><path d="M28 9v14" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/></svg><span>SlideCast <b>Studio</b></span></a>
}
const questions = [
  ['Preciso de internet para criar meus vídeos?', 'A importação de PDF e áudio, a edição multimídia e a exportação MP4 são feitas no seu computador, sem enviar esses arquivos para a nuvem. Os recursos opcionais de geração com IA precisam de conexão e da configuração do serviço correspondente.'],
  ['Quais arquivos posso usar?', 'No editor, escolha um PDF ou um vídeo MP4 como fonte visual. Adicione até quatro áudios em MP3, WAV, M4A, AAC, OGG, FLAC ou WebM. A leitura de cada arquivo é validada antes de ele entrar no projeto.'],
  ['O som do MP4 original aparece no vídeo final?', 'O áudio original do vídeo é ignorado. Você escolhe os arquivos de áudio que farão parte do resultado e ajusta o volume, o silêncio e o momento de início de cada faixa.'],
  ['Consigo continuar um projeto depois?', 'Sim. Salve seu projeto em um arquivo .slidecast para reabrir suas fontes, faixas e ajustes. Mantenha os arquivos originais nas mesmas pastas: o projeto referencia as mídias do seu computador.'],
  ['Já posso baixar ou comprar?', downloadsReady ? 'Os pacotes desktop já estão disponíveis para download. Extraia o arquivo completo antes de abrir o aplicativo. A compra e a ativação de licença desktop ainda estão em preparação; o modelo comercial não foi anunciado. A assinatura antiga do estúdio web não representa uma licença desktop.' : 'Os pacotes estão passando pelas verificações finais. Os downloads serão liberados aqui quando a publicação estiver concluída. Compra e licença desktop ainda estão em preparação.'],
  ['Como vão funcionar as atualizações e o suporte?', 'Os canais de suporte e a política de atualizações serão divulgados junto ao lançamento comercial. Ainda não há uma oferta de licença ou prazo de atualização anunciado.'],
]
function Landing() {
  return <div className="landing">
    <a className="skip-link" href="#conteudo">Pular para o conteúdo</a>
    <header className="site-header" id="inicio">
      <div className="nav-wrap"><Brand/><nav aria-label="Navegação principal">
        <a href="#recursos">Recursos</a><a href="#como-funciona">Como funciona</a><a href="#perguntas">Dúvidas</a>
      </nav><a className="button button-small" href="#disponibilidade">Baixar o desktop <Arrow/></a></div>
    </header>
    <main id="conteudo">
      <section className="hero section-wrap" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow"><span className="small-line"/> PARA QUEM TEM ALGO A ENSINAR</p>
          <h1 id="hero-title">Dê vida ao que<br/>{' '}você <em>ensina.</em></h1>
          <p className="hero-description">Suas ideias, sua voz, seu jeito de explicar. Transforme apresentações em vídeos e grave aulas em um estúdio feito para o seu computador.</p>
          <div className="hero-actions"><a className="button" href="#disponibilidade">Baixar o SlideCast <Arrow/></a><a className="text-link" href="#disponibilidade">Windows e Linux <span aria-hidden="true">↓</span></a></div>
          <div className="hero-notes"><span>PDF + vídeo + áudio</span><span>Exportação local em MP4</span></div>
        </div>
        <figure className="hero-product" id="produto">
          <div className="product-note"><span className="status-dot"/> UM ESPAÇO PARA CRIAR, DO SEU JEITO</div>
          <div className="product-window"><div className="window-top"><span className="window-dots" aria-hidden="true">● ● ●</span><span>SlideCast Studio · Criar vídeo</span><span aria-hidden="true">◧</span></div>
            <img src={productImage} alt="Captura real do SlideCast Desktop: PDF na prévia e quatro faixas de áudio com volumes e posições independentes." width="1440" height="1440" fetchPriority="high"/>
          </div>
          <figcaption>Interface real do desktop no Linux. Conteúdo da aula de demonstração.</figcaption>
          <div className="product-stamp"><span>01—04</span><p>Uma voz. Uma música.<br/>{' '}Muito mais possibilidades.</p></div>
        </figure>
      </section>
      <div className="capability-strip"><div className="section-wrap"><span>Do seu primeiro slide ao vídeo pronto.</span><p>CRIAR <i>→</i> GRAVAR <i>→</i> COMPARTILHAR</p></div></div>
      <section className="section-wrap capabilities" id="recursos" aria-labelledby="capabilities-title">
        <div className="section-heading"><p className="eyebrow">MENOS BARREIRAS. MAIS CONTEÚDO.</p><h2 id="capabilities-title">Tudo conversa.<br/>{' '}A sua aula acontece.</h2><p>Ferramentas para preparar, apresentar e finalizar seu conteúdo, sem perder o fio da explicação.</p></div>
        <div className="feature-grid">
          <article className="feature"><span className="feature-number">01 / PREPARE</span><h3>O ponto de partida<br/>{' '}é o seu material.</h3><p>Comece com páginas em PDF ou um MP4. Defina os tempos, acrescente sua narração e dê ritmo à apresentação.</p><div className="file-pair" aria-hidden="true"><span>PDF <small>PÁGINAS</small></span><i>ou</i><span>MP4 <small>VÍDEO</small></span></div></article>
          <article className="feature feature-audio"><span className="feature-number">02 / COMPONHA</span><h3>Cada som<br/>{' '}no seu lugar.</h3><p>Até quatro faixas independentes. Controle o volume, silencie ou escolha quando cada áudio começa.</p><div className="audio-example" aria-label="Exemplo ilustrativo de organização de quatro faixas"><span className="audio-voice">1 · Narração</span><span className="audio-music">2 · Música de fundo</span><span className="audio-effect">3 · Efeito</span><span className="audio-extra">4 · Complemento</span></div><small className="illustration-caption">Exemplo ilustrativo de organização</small></article>
          <article className="feature"><span className="feature-number">03 / FINALIZE</span><h3>Seu vídeo pronto.<br/>{' '}Seus arquivos com você.</h3><p>Confira a prévia com áudio, salve o projeto e exporte em MP4. O processamento acontece no seu computador.</p><div className="export-mark" aria-hidden="true"><span>↗</span><div>MP4<small>PRONTO PARA COMPARTILHAR</small></div></div></article>
        </div>
      </section>
      <section className="studio-section" aria-labelledby="studio-title"><div className="section-wrap studio-grid">
        <div className="studio-visual"><img src={studioImage} alt="Estúdio real do SlideCast com três PDFs, cenas didáticas, teleprompter e controles de gravação." width="1440" height="1200" loading="lazy"/><p>Captura real do estúdio desktop · tema escuro</p></div>
        <div className="studio-copy"><p className="eyebrow">SUA PRÓXIMA AULA TEM PALCO.</p><h2 id="studio-title">Mais presença.<br/>{' '}Mais possibilidades<br/>{' '}de explicar.</h2><p>Alterne materiais, escreva por cima dos slides e mantenha seu roteiro por perto. Os recursos didáticos acompanham a sua forma de ensinar.</p><ul><li><b>Três PDFs independentes</b><span>Cada apresentação guarda sua própria página.</span></li><li><b>Quadro, quiz, Bíblia e brainstorm</b><span>Escolha a cena que ajuda a contar a história.</span></li><li><b>Caneta e teleprompter</b><span>Faça anotações e acompanhe seu roteiro no painel do operador.</span></li></ul><p className="studio-footnote">A captura de câmera, microfone e tela depende dos dispositivos e das permissões do sistema.</p></div>
      </div></section>
      <section className="section-wrap workflow" id="como-funciona" aria-labelledby="workflow-title"><div className="workflow-intro"><p className="eyebrow">DO MATERIAL AO RESULTADO</p><h2 id="workflow-title">Um fluxo que<br/>{' '}faz sentido.</h2></div><ol><li><span>01</span><div><h3>Traga suas ideias</h3><p>Importe o PDF ou MP4 e os arquivos de áudio que vão dar vida ao conteúdo.</p></div></li><li><span>02</span><div><h3>Encontre seu ritmo</h3><p>Ajuste páginas, volumes e posições. Confira a prévia ou entre no estúdio para gravar.</p></div></li><li><span>03</span><div><h3>Compartilhe o que sabe</h3><p>Salve o projeto para continuar depois e gere um MP4 para usar onde precisar.</p></div></li></ol></section>
      <section className="section-wrap formats" aria-labelledby="formats-title"><div className="formats-heading"><p className="eyebrow">ESCOLHA O SEU FORMATO</p><h2 id="formats-title">Uma ideia pode virar muita coisa.</h2></div><div className="table-scroll"><table><caption>O que você pode produzir no SlideCast Desktop</caption><thead><tr><th scope="col">Seu objetivo</th><th scope="col">Por onde começar</th><th scope="col">O que preparar</th></tr></thead><tbody><tr><th scope="row">Vídeo com narração e música</th><td>Criar vídeo</td><td>PDF ou MP4 + até 4 áudios</td></tr><tr><th scope="row">Aula com recursos didáticos</th><td>Gravar aula</td><td>PDFs, cenas, roteiro e microfone</td></tr><tr><th scope="row">Episódio em vídeo</th><td>Podcast</td><td>Áudio gravado ou importado + capa</td></tr><tr><th scope="row">Tutorial de um aplicativo</th><td>Gravar tela / reunião</td><td>Tela e fontes de áudio do computador</td></tr></tbody></table></div></section>
      <section className="availability" id="disponibilidade" aria-labelledby="availability-title"><div className="section-wrap">
        <div className="availability-top"><div><p className="eyebrow">UM ESTÚDIO NO SEU COMPUTADOR</p><h2 id="availability-title">Sua próxima aula<br/>{' '}começa aqui.</h2></div><p>{downloadsReady ? `Baixe o SlideCast Studio ${release.version} e trabalhe` : 'A próxima versão estará disponível em breve para trabalhar'} com seus arquivos no computador. Os pacotes incluem as ferramentas para importar suas mídias e exportar em MP4.</p></div>
        <div className="platforms">
          <article><div className="platform-title"><svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true"><path d="M2 4.5 10 3.4v8H2zm10-1.4 10-1.4v9.7H12zM2 13.4h8v7.9l-8-1.1zm10 0h10v9.5l-10-1.4z" fill="currentColor"/></svg><h3>Windows</h3><span className="status-badge">v{release.version}</span></div>
            <p>Windows 10 ou 11 · 64 bits<br/>ZIP portátil{downloadsReady && ` · ${sizeLabel(windows.size_bytes)}`}</p>
            {downloadsReady ? <a className="button download-button" href={windows.url}>Baixar para Windows <span aria-hidden="true">↓</span></a> : <p className="download-pending" role="status">Download em preparação</p>}
            <p className="install-hint">Extraia o ZIP inteiro. Na pasta SlideCastStudio, abra SlideCastStudio.exe.</p>
            {downloadsReady && <a className="checksum-link" href={windows.checksum_url}>Verificação SHA256 do pacote Windows <Arrow/></a>}
          </article>
          <article><div className="platform-title"><span className="linux-icon" aria-hidden="true">&gt;_</span><h3>Linux</h3><span className="status-badge">v{release.version}</span></div>
            <p>Ubuntu 24.04 · x64<br/>TAR.GZ portátil{downloadsReady && ` · ${sizeLabel(linux.size_bytes)}`}</p>
            {downloadsReady ? <a className="button download-button" href={linux.url}>Baixar para Linux <span aria-hidden="true">↓</span></a> : <p className="download-pending" role="status">Download em preparação</p>}
            <p className="install-hint">Extraia o TAR.GZ. Na pasta SlideCastStudio, execute o arquivo SlideCastStudio.</p>
            {downloadsReady && <a className="checksum-link" href={linux.checksum_url}>Verificação SHA256 do pacote Linux <Arrow/></a>}
          </article>
        </div>
        <div className="download-details"><p>Pacotes sem assinatura comercial de código. Consulte as instruções e a compatibilidade antes de instalar.</p>{downloadsReady && <a href={release.release_url}>Notas da versão, requisitos e macOS Apple Silicon <Arrow/></a>}</div>
        <div className="license-note"><b>Compra e licença</b><p>Modelo comercial ainda não anunciado. Não há compra de licença desktop disponível nesta página.</p></div>
      </div></section>
      <section className="section-wrap faq" id="perguntas" aria-labelledby="faq-title"><div><p className="eyebrow">ANTES DE COMEÇAR</p><h2 id="faq-title">Boas perguntas.<br/>{' '}Respostas claras.</h2></div><div className="faq-list">{questions.map(([q,a])=><details key={q}><summary>{q}<span aria-hidden="true">+</span></summary><p>{a}</p></details>)}</div></section>
    </main>
    <footer className="site-footer section-wrap"><Brand/><p>Feito para dar espaço ao que você sabe.</p><a href="#perguntas">Informações e dúvidas <Arrow/></a><span>SlideCast Studio</span></footer>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Landing/></React.StrictMode>)
