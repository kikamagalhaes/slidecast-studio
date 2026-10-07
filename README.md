# SlideCast Studio 🎬📊

Aplicativo desktop multiplataforma (**Linux** e **Windows**) para criação de vídeos sincronizando apresentações de slides em **PDF** com arquivos de **áudio/narração**.

---

## ✨ Funcionalidades Principais

- **Interface Gráfica Moderna e Intuitiva**: Tema escuro profissional desenvolvido com PySide6 (Qt).
- **Arrastar e Soltar (Drag & Drop)**: Arraste arquivos PDF e faixas de áudio diretamente para a janela.
- **Visualização Prévia dos Slides**: Miniaturas geradas automaticamente de cada página da apresentação.
- **Sincronização Inteligente com IA (Google Gemini)**:
  - **Auto-Sincronização com IA**: O Gemini analisa a narração e o conteúdo dos slides para detectar a troca de assunto do apresentador e atribuir a duração exata de cada slide.
  - **Divisão Automática Uniforme**: Alternativamente, divide a duração do áudio igualmente entre todos os slides.
  - **Duração Personalizada**: Permite inspecionar e ajustar os segundos de cada slide individualmente na linha do tempo.
  - **Botão de Ajuste Rápido**: Reequilibra as durações para coincidir exatamente com a duração do áudio.
- **Exportação Flexível em Vídeo**:
  - Resoluções: 1080p Full HD (1920x1080), 720p HD, 4K Ultra HD e Quadrado (1080x1080).
  - Codec: H.264 (MP4) de alta compatibilidade para qualquer dispositivo ou plataforma (YouTube, celular, navegadores).
- **Processamento Assíncrono com Barra de Progresso Real**: Renderização em segundo plano sem travamento da interface.
- **Ações Imediatas pós-renderização**: Botões para assistir ao vídeo gerado ou abrir a pasta de destino com um clique.

---

## 🚀 Como Executar

### Pré-requisitos
- **Python 3.10+**
- **FFmpeg**:
  - **No Linux**: `sudo apt install ffmpeg` (Ubuntu/Debian) ou equivalente na sua distro.
  - **No Windows**: Baixe o FFmpeg em [ffmpeg.org](https://ffmpeg.org/download.html) e adicione ao PATH, ou simplesmente coloque o executável `ffmpeg.exe` na mesma pasta do projeto.

---

### Executando no Linux

1. Abra o terminal na pasta do projeto:
   ```bash
   ./run.sh
   ```
   *(Ou execute manualmente:)*
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python3 main.py
   ```

---

### Executando no Windows

1. Dê um duplo-clique em `run.bat` ou abra o Prompt de Comando (CMD) / PowerShell:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```

---

## 📦 Como Gerar Executável Standalone (.exe para Windows ou binário Linux)

Se desejar gerar um executável distribuível sem necessidade de o usuário final ter o Python instalado, você pode utilizar o **PyInstaller**:

```bash
pip install pyinstaller
pyinstaller --noconsole --name "SlideCast" main.py
```
O executável final estará disponível na pasta `dist/SlideCast/`.

---

## 📂 Estrutura do Código

```
VideosCreate/
├── app/
│   ├── core/
│   │   ├── audio_processor.py   # Leitura de duração e metadados de áudio (mutagen / ffprobe)
│   │   ├── ffmpeg_utils.py      # Descoberta de executáveis FFmpeg multiplataforma
│   │   ├── pdf_processor.py     # Inspeção de páginas e renderização de thumbnails (PyMuPDF)
│   │   └── video_generator.py   # Pipeline FFmpeg com concat demuxer e monitoramento de progresso
│   ├── ui/
│   │   ├── main_window.py       # Janela principal, controles e eventos
│   │   ├── styles.py            # Folha de estilo visual (QSS escuro)
│   │   └── widgets.py           # Cards de Drag & Drop e miniaturas dos slides
│   └── worker.py                # Thread em segundo plano (QThread) para renderização fluida
├── main.py                      # Ponto de entrada do aplicativo
├── requirements.txt             # Dependências Python
├── run.sh                       # Script de inicialização para Linux
├── run.bat                      # Script de inicialização para Windows
└── README.md                    # Documentação do projeto
```
