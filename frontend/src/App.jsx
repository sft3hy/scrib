import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Camera, UploadCloud, RefreshCw, FileText, Clipboard, Download,
  Settings, CheckCircle, AlertCircle, Play, Square, History,
  Settings2, Eye, Cpu, HelpCircle, HardDrive, ChevronLeft, ChevronRight, Menu
} from 'lucide-react'
import { marked } from 'marked'
import peelyImg from './assets/peely.png'

// Custom marked renderer: rewrite backend /output/* image paths to absolute backend URL
const renderer = new marked.Renderer()
const BACKEND = ''
renderer.image = (token) => {
  // marked v5+ passes a token object { href, title, text }
  const href = (token && typeof token === 'object') ? token.href : token
  const text = (token && typeof token === 'object') ? (token.text || '') : ''
  const title = (token && typeof token === 'object') ? (token.title || '') : ''
  
  let src = href || ''
  if (typeof href === 'string') {
    const outputIdx = href.indexOf('/output/')
    if (outputIdx !== -1) {
      src = `${BACKEND}${href.substring(outputIdx)}`
    }
  }
  return `<img src="${src}" alt="${text}" title="${title}" style="max-width:100%;border-radius:8px;margin:12px 0;" />`
}
marked.use({ renderer })

// Small inline tooltip shown on hover over the ⓘ icon
const InfoTooltip = ({ text }) => {
  const [visible, setVisible] = useState(false)
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', cursor: 'help', marginLeft: '4px' }}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', userSelect: 'none' }}>ⓘ</span>
      {visible && (
        <div style={{
          position: 'absolute',
          bottom: 'calc(100% + 6px)',
          left: '50%',
          transform: 'translateX(-50%)',
          background: '#1a1d28',
          border: '1px solid rgba(255,255,255,0.12)',
          borderRadius: '8px',
          padding: '8px 12px',
          fontSize: '0.75rem',
          color: 'rgba(255,255,255,0.85)',
          width: '220px',
          lineHeight: '1.45',
          zIndex: 9999,
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
          pointerEvents: 'none',
          whiteSpace: 'normal',
        }}>
          {text}
        </div>
      )}
    </span>
  )
}

const BananaIcon = () => (
  <img src={peelyImg} alt="Peely" style={{ width: '48px', height: '48px', objectFit: 'contain' }} />
)

function App() {
  // Resizable and Collapsible Sidebar State
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem('scrib_sidebar_width')
    return saved ? parseInt(saved, 10) : 320
  })
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem('scrib_sidebar_collapsed')
    return saved === 'true'
  })
  const [isResizing, setIsResizing] = useState(false)

  // Save to localStorage when changed
  useEffect(() => {
    localStorage.setItem('scrib_sidebar_width', sidebarWidth.toString())
  }, [sidebarWidth])

  useEffect(() => {
    localStorage.setItem('scrib_sidebar_collapsed', isSidebarCollapsed.toString())
  }, [isSidebarCollapsed])

  const startResizing = useCallback((mouseDownEvent) => {
    setIsResizing(true)
  }, [])

  const stopResizing = useCallback(() => {
    setIsResizing(false)
  }, [])

  const resize = useCallback((mouseMoveEvent) => {
    if (isResizing) {
      const newWidth = Math.max(200, Math.min(600, mouseMoveEvent.clientX))
      setSidebarWidth(newWidth)
    }
  }, [isResizing])

  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', resize)
      window.addEventListener('mouseup', stopResizing)
    }
    return () => {
      window.removeEventListener('mousemove', resize)
      window.removeEventListener('mouseup', stopResizing)
    }
  }, [isResizing, resize, stopResizing])

  // Config state
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmApiBase, setLlmApiBase] = useState('http://localhost:11434/v1')
  const [modelName, setModelName] = useState('meta-llama/llama-4-scout-17b-16e-instruct')
  const [similarityThreshold, setSimilarityThreshold] = useState(0.85)
  const [minTime, setMinTime] = useState(0.5)
  const [showSettings, setShowSettings] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')

  // Video state
  const [videoFile, setVideoFile] = useState(null)
  const [videoPath, setVideoPath] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [isUploading, setIsUploading] = useState(false)

  // Screen Recording State
  const [isRecording, setIsRecording] = useState(false)
  const [recDuration, setRecDuration] = useState(0)
  const streamRef = useRef(null)
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)

  // Pipeline processing state
  const [isProcessing, setIsProcessing] = useState(false)
  const [progressState, setProgressState] = useState('idle') // idle, uploading, starting, detecting, screenshots, analyzing, generating, completed
  const [progressMessage, setProgressMessage] = useState('')
  const [currentStep, setCurrentStep] = useState(0)
  const [totalSteps, setTotalSteps] = useState(0)
  const [error, setError] = useState('')

  // Output Result
  const [markdownResult, setMarkdownResult] = useState('')
  const [screenshots, setScreenshots] = useState({})
  const [docUrl, setDocUrl] = useState('')
  const [activeTab, setActiveTab] = useState('guide') // guide, screenshots, video

  // App history
  const [history, setHistory] = useState([])

  // Load Settings and History on Mount
  useEffect(() => {
    fetchSettings()
    loadHistory()
  }, [])

  const fetchSettings = async () => {
    try {
      const res = await fetch('/api/settings')
      if (res.ok) {
        const data = await res.json()
        setLlmApiKey(data.llm_api_key || '')
        setLlmApiBase(data.llm_api_base || 'http://localhost:11434/v1')
        setModelName(data.model_name || 'gemma4:latest')
        setSimilarityThreshold(data.similarity_threshold || 0.85)
        setMinTime(data.min_time_between_steps || 1.0)
      }
    } catch (err) {
      console.error("Error fetching settings:", err)
    }
  }

  const handleSaveSettings = async (e) => {
    e.preventDefault()
    setSaveStatus('Saving...')
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          llm_api_key: llmApiKey,
          llm_api_base: llmApiBase,
          model_name: modelName,
          similarity_threshold: similarityThreshold,
          min_time_between_steps: minTime
        })
      })
      if (res.ok) {
        setSaveStatus('Saved!')
        setTimeout(() => setSaveStatus(''), 2000)
      } else {
        setSaveStatus('Failed to save')
      }
    } catch (err) {
      setSaveStatus('Error saving')
      console.error(err)
    }
  }

  const loadHistory = () => {
    const saved = localStorage.getItem('screendoc_history')
    if (saved) {
      try {
        setHistory(JSON.parse(saved))
      } catch (e) {
        console.error("Error parsing history:", e)
      }
    }
  }

  const saveToHistory = (item) => {
    const saved = localStorage.getItem('screendoc_history')
    let currentHistory = []
    if (saved) {
      try {
        currentHistory = JSON.parse(saved)
      } catch (e) { }
    }
    const updated = [item, ...currentHistory.slice(0, 9)] // Limit to 10 entries
    localStorage.setItem('screendoc_history', JSON.stringify(updated))
    setHistory(updated)
  }

  const deleteFromHistory = (idx) => {
    const updated = history.filter((_, i) => i !== idx)
    localStorage.setItem('screendoc_history', JSON.stringify(updated))
    setHistory(updated)
  }

  const extractTitle = (md) => {
    const match = md.match(/^#\s+(.+)$/m)
    return match ? match[1] : 'How-To Guide'
  }

  // Handle Drag & Drop / Upload
  const handleFileUpload = async (file) => {
    if (!file) return
    setVideoFile(file)
    setError('')
    setProgressState('uploading')
    setIsUploading(true)
    setIsProcessing(true)
    setProgressMessage('Initializing...')

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      })
      if (!res.ok) throw new Error("Upload failed")

      const data = await res.json()
      setVideoPath(data.path)
      setVideoUrl(data.url)
      setIsUploading(false)

      // Auto-trigger documentation generation
      triggerGeneration(data.path)
    } catch (err) {
      setError("Failed to upload video: " + err.message)
      setIsUploading(false)
      setIsProcessing(false)
      setProgressState('idle')
    }
  }

  // Start Screen Recording
  const startRecording = async () => {
    setError('')
    chunksRef.current = []
    setRecDuration(0)

    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 15, cursor: 'always' },
        audio: false
      })

      streamRef.current = stream

      // Select Codec
      let mimeType = 'video/webm;codecs=vp9'
      if (!MediaRecorder.isTypeSupported(mimeType)) mimeType = 'video/webm;codecs=vp8'
      if (!MediaRecorder.isTypeSupported(mimeType)) mimeType = 'video/webm'

      const mediaRecorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 2500000 })
      mediaRecorderRef.current = mediaRecorder

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunksRef.current.push(e.data)
        }
      }

      mediaRecorder.onstop = async () => {
        clearInterval(timerRef.current)
        setIsRecording(false)
        setProgressState('uploading')
        setIsUploading(true)
        setIsProcessing(true)
        setProgressMessage('Initializing...')

        const blob = new Blob(chunksRef.current, { type: mimeType })
        const recordingFile = new File([blob], "recording.webm", { type: mimeType })

        // Upload
        const formData = new FormData()
        formData.append('file', recordingFile)

        try {
          const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData
          })
          if (!res.ok) throw new Error("Upload failed")

          const data = await res.json()
          setVideoPath(data.path)
          setVideoUrl(data.url)
          setIsUploading(false)

          // Trigger generation
          triggerGeneration(data.path)
        } catch (err) {
          setError("Failed to save and upload recording: " + err.message)
          setIsUploading(false)
          setIsProcessing(false)
          setProgressState('idle')
        }
      }

      // Handle user clicking browser stop sharing button
      stream.getVideoTracks()[0].onended = () => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
        stream.getTracks().forEach(t => t.stop())
      }

      mediaRecorder.start(1000)
      setIsRecording(true)

      // Timer setup
      timerRef.current = setInterval(() => {
        setRecDuration(prev => prev + 1)
      }, 1000)

    } catch (err) {
      setError("Could not launch screen capture. Please ensure permissions are granted.")
      console.error(err)
    }
  }

  // Stop Screen Recording
  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
    }
  }

  // Run Backend Pipeline
  const triggerGeneration = async (path) => {
    setIsProcessing(true)
    setError('')
    setProgressState('starting')
    setProgressMessage('Connecting to backend processing node...')
    setMarkdownResult('')

    try {
      const response = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: path,
          similarity_threshold: similarityThreshold,
          min_time_between_steps: minTime
        })
      })

      if (!response.ok) throw new Error("Processing server returned error state.")

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const data = JSON.parse(line)

            if (data.status === 'starting') {
              setProgressState('starting')
              setProgressMessage(data.message)
            } else if (data.status === 'detecting') {
              setProgressState('detecting')
              setProgressMessage(data.message)
            } else if (data.status === 'saving_screenshots') {
              setProgressState('screenshots')
              setProgressMessage(data.message)
            } else if (data.status === 'analyzing_step') {
              setProgressState('analyzing')
              setProgressMessage(data.message)
              setCurrentStep(data.current)
              setTotalSteps(data.total)
            } else if (data.status === 'generating_guide') {
              setProgressState('generating')
              setProgressMessage(data.message)
            } else if (data.status === 'completed') {
              setProgressState('completed')
              setProgressMessage(data.message)
              setMarkdownResult(data.markdown)
              setScreenshots(data.screenshots)
              setDocUrl(data.doc_url)

              // Save to localStorage history
              saveToHistory({
                title: extractTitle(data.markdown),
                markdown: data.markdown,
                screenshots: data.screenshots,
                docUrl: data.doc_url,
                videoUrl: videoUrl,
                timestamp: new Date().toLocaleString()
              })
              setIsProcessing(false)
            } else if (data.status === 'error') {
              setError(data.message)
              setIsProcessing(false)
              setProgressState('idle')
            }
          } catch (e) {
            console.error("JSON parse error on line:", line, e)
          }
        }
      }
    } catch (err) {
      setError("Processing pipeline aborted: " + err.message)
      setIsProcessing(false)
      setProgressState('idle')
    }
  }

  const formatTime = (secs) => {
    const m = String(Math.floor(secs / 60)).padStart(2, '0')
    const s = String(secs % 60).padStart(2, '0')
    return `${m}:${s}`
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(markdownResult)
    alert("Markdown copied to clipboard!")
  }

  const loadFromHistory = (item) => {
    setMarkdownResult(item.markdown)
    setScreenshots(item.screenshots)
    setDocUrl(item.docUrl)
    setVideoUrl(item.videoUrl || '')
    setProgressState('completed')
    setActiveTab('guide')
  }

  const resetAll = () => {
    setVideoFile(null)
    setVideoPath('')
    setVideoUrl('')
    setMarkdownResult('')
    setScreenshots({})
    setDocUrl('')
    setProgressState('idle')
    setProgressMessage('')
    setCurrentStep(0)
    setTotalSteps(0)
    setError('')
  }

  // Stage details for timeline
  const stages = [
    { id: 'uploading', label: 'Video Upload', desc: 'Copying video to storage' },
    { id: 'detecting', label: 'UI State Analysis', desc: 'Locating transitions and clicks' },
    { id: 'screenshots', label: 'Snapshot Extraction', desc: 'Saving relevant UI states' },
    { id: 'analyzing', label: 'AI Frame Inspection', desc: `LLM Vision processing actions (${currentStep}/${totalSteps})` },
    { id: 'generating', label: 'Guide Synthesis', desc: 'Compiling structured How-To guide' }
  ]

  const getCurrentStageIndex = () => {
    if (progressState === 'uploading') return 0
    if (progressState === 'detecting') return 1
    if (progressState === 'screenshots') return 2
    if (progressState === 'analyzing') return 3
    if (progressState === 'generating') return 4
    if (progressState === 'completed') return 5
    return -1
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', width: '100vw', position: 'relative' }}>

      {/* Expand Sidebar Floating Button */}
      {isSidebarCollapsed && (
        <button
          onClick={() => setIsSidebarCollapsed(false)}
          title="Expand Sidebar"
          style={{
            position: 'absolute',
            left: '16px',
            top: '16px',
            zIndex: 100,
            background: 'var(--bg-sidebar)',
            border: '1px solid var(--border-normal)',
            borderRadius: '8px',
            padding: '8px',
            color: '#fff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 10px rgba(0,0,0,0.3)',
            transition: 'all 0.2s'
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--bg-sidebar)' }}
        >
          <Menu size={20} />
        </button>
      )}

      {/* Sidebar Panel */}
      <aside style={{
        width: isSidebarCollapsed ? '0px' : `${sidebarWidth}px`,
        minWidth: isSidebarCollapsed ? '0px' : `${sidebarWidth}px`,
        background: 'var(--bg-sidebar)',
        borderRight: isSidebarCollapsed ? 'none' : '1px solid var(--border-normal)',
        padding: isSidebarCollapsed ? '0px' : '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
        overflowY: 'auto',
        overflowX: 'hidden',
        transition: isResizing ? 'none' : 'width 0.2s, padding 0.2s, min-width 0.2s',
        position: 'relative'
      }}>
        {!isSidebarCollapsed && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  background: 'linear-gradient(135deg, #fee22f 0%, #eab308 100%)',
                  borderRadius: '10px',
                  padding: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: '0 0 10px rgba(254, 226, 47, 0.3)'
                }}>
                  <BananaIcon />
                </div>
                <div>
                  <h1 style={{ fontSize: '1.4rem', fontWeight: 800, letterSpacing: '0.5px', color: '#fff', fontFamily: 'var(--font-display)' }}>Scrib</h1>
                  <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', fontWeight: 600 }}>AI HOW-TO</p>
                </div>
              </div>
              <button
                onClick={() => setIsSidebarCollapsed(true)}
                title="Collapse Sidebar"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-text-muted)',
                  cursor: 'pointer',
                  padding: '6px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s'
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = '#fff' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)' }}
              >
                <ChevronLeft size={18} />
              </button>
            </div>

            <hr style={{ border: 'none', borderTop: '1px solid var(--border-normal)' }} />

            {/* History Widget */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', flexGrow: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#fff', fontSize: '0.9rem', fontWeight: 600 }}>
                <History size={16} />
                <span>Recent Documents</span>
              </div>
              {history.length === 0 ? (
                <div style={{
                  fontSize: '0.8rem',
                  color: 'var(--color-text-muted)',
                  padding: '16px',
                  textAlign: 'center',
                  background: 'rgba(255,255,255,0.02)',
                  borderRadius: '8px',
                  border: '1px dashed var(--border-normal)'
                }}>
                  No guides generated yet
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {history.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-normal)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.15)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-normal)' }}
                    >
                      <button
                        onClick={() => loadFromHistory(item)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          padding: 0,
                          textAlign: 'left',
                          color: '#fff',
                          cursor: 'pointer',
                          flexGrow: 1,
                          minWidth: 0
                        }}
                      >
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {item.title}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', marginTop: '4px' }}>
                          {item.timestamp}
                        </div>
                      </button>
                      <button
                        onClick={() => deleteFromHistory(idx)}
                        title="Delete"
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--color-text-muted)',
                          cursor: 'pointer',
                          padding: '4px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          lineHeight: 1,
                          flexShrink: 0,
                          transition: 'color 0.15s'
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--color-coral)' }}
                        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--color-text-muted)' }}
                      >✕</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Settings Panel */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                onClick={() => setShowSettings(!showSettings)}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border-normal)',
                  borderRadius: '8px',
                  padding: '10px 16px',
                  color: '#fff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  fontWeight: 500,
                  fontSize: '0.9rem',
                  width: '100%',
                  cursor: 'pointer'
                }}
              >
                <Settings size={16} />
                <span>Configure Settings</span>
              </button>

              {showSettings && (
                <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '4px' }}>
                  <form onSubmit={handleSaveSettings} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <div>
                      <label style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', display: 'block', marginBottom: '4px' }}>Model</label>
                      <select
                        className="custom-select"
                        value={modelName}
                        onChange={(e) => setModelName(e.target.value)}
                      >
                        <option value="gemma4:latest">gemma4:latest</option>
                        <option value="gemma4:26b">gemma4:26b</option>
                        <option value="qwen3.5:2b">qwen3.5:2b</option>
                        <option value="x/flux2-klein:9b">x/flux2-klein:9b</option>
                        <option value="nomic-embed-text:latest">nomic-embed-text:latest</option>
                        <option value="meta-llama/llama-4-scout-17b-16e-instruct">meta-llama/llama-4-scout-17b-16e-instruct (Groq)</option>
                        {modelName && !['gemma4:latest', 'gemma4:26b', 'qwen3.5:2b', 'x/flux2-klein:9b', 'nomic-embed-text:latest', 'meta-llama/llama-4-scout-17b-16e-instruct'].includes(modelName) && (
                          <option value={modelName}>{modelName} (Current)</option>
                        )}
                      </select>
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: '4px' }}>
                        <label>Frame Similarity ({similarityThreshold})</label>
                        <InfoTooltip text="Determines how different frames must be to count as a new step. Lower = fewer steps (ignores minor UI changes). Higher = more steps (catches subtle changes)." />
                      </div>
                      <input
                        type="range"
                        min="0.5"
                        max="1.0"
                        step="0.05"
                        className="custom-slider"
                        value={similarityThreshold}
                        onChange={(e) => setSimilarityThreshold(parseFloat(e.target.value))}
                      />
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: '4px' }}>
                        <label>Min Interval ({minTime}s)</label>
                        <InfoTooltip text="Minimum seconds between captured steps. Higher = ignore rapid actions close together. Lower = capture quick transitions more accurately." />
                      </div>
                      <input
                        type="range"
                        min="0.1"
                        max="5.0"
                        step="0.1"
                        className="custom-slider"
                        value={minTime}
                        onChange={(e) => setMinTime(parseFloat(e.target.value))}
                      />
                    </div>
                    <button
                      type="submit"
                      style={{
                        background: 'var(--color-coral)',
                        color: '#6e6b6bff',
                        border: 'none',
                        borderRadius: '6px',
                        padding: '8px 12px',
                        fontSize: '0.85rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        width: '100%',
                        marginTop: '4px'
                      }}
                    >
                      Save Configuration
                    </button>
                    {saveStatus && (
                      <div style={{ textAlign: 'center', fontSize: '0.75rem', color: 'var(--color-cyan)', fontWeight: 600 }}>
                        {saveStatus}
                      </div>
                    )}
                  </form>
                </div>
              )}
            </div>
          </>
        )}
      </aside>

      {/* Resizer Handle */}
      {!isSidebarCollapsed && (
        <div
          onMouseDown={startResizing}
          style={{
            width: '4px',
            cursor: 'col-resize',
            background: isResizing ? 'var(--color-coral)' : 'transparent',
            transition: 'background 0.2s',
            zIndex: 10,
            userSelect: 'none'
          }}
          onMouseEnter={(e) => { if (!isResizing) e.currentTarget.style.background = 'rgba(255,255,255,0.1)' }}
          onMouseLeave={(e) => { if (!isResizing) e.currentTarget.style.background = 'transparent' }}
        />
      )}

      {/* Main Workspace Area */}
      <main style={{
        flexGrow: 1,
        padding: '40px',
        display: 'flex',
        flexDirection: 'column',
        gap: '32px',
        overflowY: 'auto',
        maxHeight: '100vh'
      }}>

        {/* Step 1: Upload or Record View */}
        {progressState === 'idle' && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            flexGrow: 1,
            gap: '32px',
            maxWidth: '800px',
            margin: '0 auto',
            width: '100%'
          }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '2.5rem', fontWeight: 800, color: '#fff', marginBottom: '8px' }}>Create How-To Guides</h2>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '1.1rem' }}>Record your screen or upload a video workflow, and AI does the rest.</p>
            </div>

            {error && (
              <div style={{
                background: 'rgba(255, 75, 75, 0.1)',
                border: '1px solid var(--color-coral)',
                borderRadius: '8px',
                padding: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                color: '#fff',
                width: '100%',
                fontSize: '0.9rem'
              }}>
                <AlertCircle color="var(--color-coral)" size={20} />
                <span>{error}</span>
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', width: '100%' }}>

              {/* Record Card */}
              <div
                className="glass-panel"
                style={{
                  padding: '40px 32px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '20px',
                  textAlign: 'center',
                  position: 'relative',
                  overflow: 'hidden'
                }}
              >
                <div style={{
                  borderRadius: '50%',
                  background: isRecording ? 'rgba(255, 75, 75, 0.1)' : 'rgba(255, 255, 255, 0.03)',
                  border: isRecording ? '2px solid var(--color-coral)' : '1px solid var(--border-normal)',
                  padding: '24px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }} className={isRecording ? 'recording-pulse' : ''}>
                  <Camera size={36} color={isRecording ? 'var(--color-coral)' : '#fff'} />
                </div>
                <div>
                  <h3 style={{ fontSize: '1.25rem', color: '#fff', fontWeight: 700, marginBottom: '6px' }}>Screen Recorder</h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Perform actions directly. We'll automatically identify each step.</p>
                </div>
                {isRecording ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', width: '100%', alignItems: 'center' }}>
                    <div style={{ color: 'var(--color-coral)', fontWeight: 700, fontSize: '1.2rem', fontFamily: 'monospace' }}>
                      ● {formatTime(recDuration)}
                    </div>
                    <button
                      onClick={stopRecording}
                      style={{
                        background: '#fff',
                        color: '#000',
                        border: 'none',
                        borderRadius: '8px',
                        padding: '12px 24px',
                        fontWeight: 700,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        fontSize: '0.95rem'
                      }}
                    >
                      <Square size={16} fill="#000" />
                      <span>Stop &amp; Build Guide</span>
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={startRecording}
                    style={{
                      background: 'var(--color-coral)',
                      color: '#313131ff',
                      border: 'none',
                      borderRadius: '8px',
                      padding: '12px 24px',
                      fontWeight: 700,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '0.95rem',
                      width: '100%',
                      justifyContent: 'center'
                    }}
                  >
                    <Play size={16} fill="#fff" />
                    <span>Start Recording</span>
                  </button>
                )}
              </div>

              {/* Upload Card */}
              <div
                className="glass-panel"
                style={{
                  padding: '40px 32px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '20px',
                  textAlign: 'center',
                  cursor: 'pointer'
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                    handleFileUpload(e.dataTransfer.files[0])
                  }
                }}
              >
                <div style={{
                  borderRadius: '50%',
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid var(--border-normal)',
                  padding: '24px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  <UploadCloud size={36} color="#fff" />
                </div>
                <div>
                  <h3 style={{ fontSize: '1.25rem', color: '#fff', fontWeight: 700, marginBottom: '6px' }}>Upload Video</h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Drag and drop files, or browse. Supports MP4, WebM, MOV.</p>
                </div>
                <input
                  type="file"
                  id="file-input"
                  accept="video/*"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      handleFileUpload(e.target.files[0])
                    }
                  }}
                  style={{ display: 'none' }}
                />
                <button
                  onClick={() => document.getElementById('file-input').click()}
                  style={{
                    background: 'transparent',
                    color: '#fff',
                    border: '1px solid var(--border-normal)',
                    borderRadius: '8px',
                    padding: '12px 24px',
                    fontWeight: 700,
                    cursor: 'pointer',
                    fontSize: '0.95rem',
                    width: '100%',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                >
                  <span>Select Video File</span>
                </button>
              </div>

            </div>
          </div>
        )}

        {/* Step 2: Processing Timeline View */}
        {isProcessing && (
          <div style={{
            maxWidth: '650px',
            margin: '0 auto',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: '32px',
            flexGrow: 1,
            justifyContent: 'center'
          }}>
            <div style={{ textAlign: 'center' }}>
              <RefreshCw size={48} className="recording-pulse" color="var(--color-coral)" style={{ animation: 'spin 2s linear infinite', margin: '0 auto 16px auto', borderRadius: '50%' }} />
              <h2 style={{ fontSize: '1.75rem', fontWeight: 800, color: '#fff', marginBottom: '8px' }}>Processing Pipeline Active</h2>
              <p style={{ color: 'var(--color-cyan)', fontSize: '0.95rem', fontWeight: 600 }}>{progressMessage}</p>
            </div>

            {/* Custom progress timeline */}
            <div className="glass-panel" style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {stages.map((stage, idx) => {
                const currentStageIdx = getCurrentStageIndex()
                const isCompleted = idx < currentStageIdx
                const isActive = idx === currentStageIdx

                return (
                  <div key={stage.id} style={{ display: 'flex', gap: '16px', position: 'relative' }}>

                    {/* Connecting line */}
                    {idx < stages.length - 1 && (
                      <div style={{
                        position: 'absolute',
                        left: '11px',
                        top: '24px',
                        bottom: '-16px',
                        width: '2px',
                        background: isCompleted ? 'var(--color-success)' : 'var(--border-normal)'
                      }} />
                    )}

                    <div style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '50%',
                      border: '2px solid',
                      borderColor: isCompleted ? 'var(--color-success)' : isActive ? 'var(--color-coral)' : 'var(--border-normal)',
                      background: isCompleted ? 'var(--color-success)' : '#07080d',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      zIndex: 2
                    }}>
                      {isCompleted ? (
                        <CheckCircle size={14} color="#fff" />
                      ) : isActive ? (
                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--color-coral)' }} />
                      ) : null}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{
                        fontSize: '0.95rem',
                        fontWeight: 700,
                        color: isCompleted ? '#fff' : isActive ? 'var(--color-coral)' : 'var(--color-text-muted)'
                      }}>
                        {stage.label}
                      </span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                        {stage.desc}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Step 3: Finished Result Guide View */}
        {progressState === 'completed' && markdownResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', width: '100%', flexGrow: 1 }}>

            {/* Top Toolbar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#fff' }}>Generated How-To Guide</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>Read, copy, or export your custom help documentation.</p>
              </div>
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={resetAll}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border-normal)',
                    borderRadius: '8px',
                    padding: '8px 16px',
                    color: '#fff',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <RefreshCw size={14} />
                  <span>Start New</span>
                </button>
                <button
                  onClick={handleCopy}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border-normal)',
                    borderRadius: '8px',
                    padding: '8px 16px',
                    color: '#fff',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}
                >
                  <Clipboard size={14} />
                  <span>Copy Markdown</span>
                </button>
                <a
                  href={docUrl}
                  download
                  style={{ textDecoration: 'none' }}
                >
                  <button
                    style={{
                      background: 'var(--color-coral)',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '8px',
                      padding: '8px 16px',
                      fontSize: '0.9rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}
                  >
                    <Download size={14} />
                    <span>Download Guide</span>
                  </button>
                </a>
              </div>
            </div>

            {/* Tab Controller */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border-normal)', gap: '24px' }}>
              <button
                onClick={() => setActiveTab('guide')}
                style={{
                  background: 'transparent',
                  border: 'none',
                  borderBottom: activeTab === 'guide' ? '2px solid var(--color-coral)' : '2px solid transparent',
                  padding: '12px 8px',
                  color: activeTab === 'guide' ? '#fff' : 'var(--color-text-muted)',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '0.95rem'
                }}
              >
                <FileText size={16} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                <span>Interactive Guide</span>
              </button>
              <button
                onClick={() => setActiveTab('screenshots')}
                style={{
                  background: 'transparent',
                  border: 'none',
                  borderBottom: activeTab === 'screenshots' ? '2px solid var(--color-coral)' : '2px solid transparent',
                  padding: '12px 8px',
                  color: activeTab === 'screenshots' ? '#fff' : 'var(--color-text-muted)',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '0.95rem'
                }}
              >
                <Eye size={16} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                <span>Detected Steps ({Object.keys(screenshots).length})</span>
              </button>
              {videoUrl && (
                <button
                  onClick={() => setActiveTab('video')}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    borderBottom: activeTab === 'video' ? '2px solid var(--color-coral)' : '2px solid transparent',
                    padding: '12px 8px',
                    color: activeTab === 'video' ? '#fff' : 'var(--color-text-muted)',
                    cursor: 'pointer',
                    fontWeight: 600,
                    fontSize: '0.95rem'
                  }}
                >
                  <Play size={16} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                  <span>Raw Video</span>
                </button>
              )}
            </div>

            {/* Main Tabs Display */}
            <div className="glass-panel" style={{ padding: '32px', flexGrow: 1, minHeight: '400px' }}>

              {/* Guide Markdown Tab */}
              {activeTab === 'guide' && (
                <div
                  className="markdown-body"
                  dangerouslySetInnerHTML={{ __html: marked(markdownResult) }}
                />
              )}

              {/* Screenshots List Tab */}
              {activeTab === 'screenshots' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '24px' }}>
                  {Object.entries(screenshots).map(([idx, url]) => {
                    let fullUrl = url
                    if (typeof url === 'string') {
                      const outputIdx = url.indexOf('/output/')
                      if (outputIdx !== -1) {
                        fullUrl = `${BACKEND}${url.substring(outputIdx)}`
                      }
                    }
                    return (
                      <div
                        key={idx}
                        style={{
                          background: 'rgba(0,0,0,0.2)',
                          border: '1px solid var(--border-normal)',
                          borderRadius: '12px',
                          overflow: 'hidden',
                          display: 'flex',
                          flexDirection: 'column'
                        }}
                      >
                        <img
                          src={fullUrl}
                          alt={`Step ${parseInt(idx) + 1}`}
                          style={{ width: '100%', height: '180px', objectFit: 'cover', borderBottom: '1px solid var(--border-normal)', margin: 0, borderRadius: 0 }}
                        />
                        <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 700, fontSize: '0.9rem', color: '#fff' }}>Step {parseInt(idx) + 1}</span>
                          <a
                            href={fullUrl}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: 'var(--color-cyan)', fontSize: '0.8rem', textDecoration: 'none', fontWeight: 600 }}
                          >
                            View Fullscreen
                          </a>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Video Preview Tab */}
              {activeTab === 'video' && videoUrl && (
                <div style={{ width: '100%', maxWidth: '800px', margin: '0 auto' }}>
                  <video
                    key={videoUrl}
                    src={videoUrl.startsWith('/output') ? `${BACKEND}${videoUrl}` : videoUrl}
                    controls
                    playsInline
                    preload="auto"
                    style={{ width: '100%', borderRadius: '12px', border: '1px solid var(--border-normal)', boxShadow: '0 4px 20px rgba(0,0,0,0.5)' }}
                  />
                </div>
              )}

            </div>
          </div>
        )}

      </main>
    </div>
  )
}

export default App
