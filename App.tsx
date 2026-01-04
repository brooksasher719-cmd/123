import React, { useState, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { 
  Upload, FileAudio, List, ArrowRight, Loader2, Key, FileText, 
  Play, Download, Copy, Check, Cloud, CloudFog, Save, Layout, Sparkles, ChevronDown,
  WifiOff, PauseCircle
} from 'lucide-react';
import saveAs from 'file-saver';
import { marked } from 'marked';
import MediaPlayer from './components/MediaPlayer';
import StageManager from './components/StageManager';
import RichTextEditor from './components/RichTextEditor';
import FileManager from './components/FileManager'; // Import FileManager
import { MediaItem, ProcessingStage, Version } from './types';
import { transcribeSegment, processTextStage, decodeAudioFile, sliceAudioBuffer, blobToBase64 } from './services/geminiService';
import { saveProjectToSupabase } from './services/supabaseClient';

const CHUNK_DURATION = 240; // 4 minutes in seconds

// List of available models - Expanded to include ALL versions
const AVAILABLE_MODELS = [
  { id: 'gemini-3-pro-preview', name: 'Gemini 3.0 Pro (هوشمندترین)' },
  { id: 'gemini-3-flash-preview', name: 'Gemini 3.0 Flash (نسخه جدید)' },
  { id: 'gemini-2.5-pro-preview', name: 'Gemini 2.5 Pro (بسیار قدرتمند)' },
  { id: 'gemini-2.5-flash-preview', name: 'Gemini 2.5 Flash (تعادل عالی)' },
  { id: 'gemini-2.0-flash-exp', name: 'Gemini 2.0 Flash (پرسرعت)' },
  { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro (دقیق و پایدار)' },
  { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash (اقتصادی)' },
  { id: 'gemini-1.5-flash-8b', name: 'Gemini 1.5 Flash-8B (بسیار سبک)' },
];

const App: React.FC = () => {
  const [apiKey, setApiKey] = useState(process.env.API_KEY || '');
  const [mediaQueue, setMediaQueue] = useState<MediaItem[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [showKeyModal, setShowKeyModal] = useState(!process.env.API_KEY);
  const [copySuccess, setCopySuccess] = useState(false);
  const [showFileManager, setShowFileManager] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>('gemini-2.5-pro-preview');
  
  // Cloud Sync States
  const [syncStatus, setSyncStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const lastSavedRef = useRef<number>(Date.now());
  
  // Ref for handling auto-resume logic without stale closures
  const mediaQueueRef = useRef<MediaItem[]>([]); 
  useEffect(() => { mediaQueueRef.current = mediaQueue; }, [mediaQueue]);

  const activeItem = mediaQueue.find(i => i.id === activeItemId) || null;

  // Initial check for API Key
  useEffect(() => {
    if (!apiKey) setShowKeyModal(true);
  }, [apiKey]);

  // AUTO-SAVE LOGIC
  useEffect(() => {
    const interval = setInterval(() => {
      // Logic: ONLY save if the item is explicitly 'completed'.
      // Do NOT save if 'idle', 'processing', 'paused', or 'error'.
      if (activeItem && activeItem.status === 'completed' && syncStatus !== 'saving') {
        const now = Date.now();
        if (now - lastSavedRef.current > 30000) {
           handleSaveToCloud(activeItem, true);
        }
      }
    }, 10000); // Check every 10 seconds

    return () => clearInterval(interval);
  }, [activeItem, syncStatus]);

  // NETWORK RECONNECTION LISTENER
  useEffect(() => {
    const handleOnline = () => {
      console.log("Network back online. Checking for paused items...");
      const pausedItem = mediaQueueRef.current.find(i => i.status === 'paused');
      if (pausedItem && apiKey) {
        console.log("Resuming item:", pausedItem.id);
        startTranscription(pausedItem, true); // true for resume mode
      }
    };
    
    window.addEventListener('online', handleOnline);
    return () => window.removeEventListener('online', handleOnline);
  }, [apiKey]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files: File[] = Array.from(e.target.files);
      const newItems: MediaItem[] = files.map((file) => ({
        id: uuidv4(),
        file: file,
        duration: 0,
        status: 'idle',
        progress: 0,
        currentVersionId: null,
        versions: [],
        processedChunks: 0,
        totalChunks: 0
      }));
      setMediaQueue(prev => [...prev, ...newItems]);
      if (!activeItemId && newItems.length > 0) {
        setActiveItemId(newItems[0].id);
      }
    }
  };

  const handleLoadProject = (item: MediaItem) => {
    // Check if already exists
    const exists = mediaQueue.find(i => i.id === item.id);
    if (!exists) {
      setMediaQueue(prev => [...prev, item]);
    }
    setActiveItemId(item.id);
  };

  const handleSaveToCloud = async (item: MediaItem, isAuto = false) => {
    if (!item) return;
    try {
      setSyncStatus('saving');
      await saveProjectToSupabase(item);
      setSyncStatus('saved');
      lastSavedRef.current = Date.now();
      if (!isAuto) {
        setTimeout(() => setSyncStatus('idle'), 3000);
      }
    } catch (err) {
      console.error('Save failed', err);
      setSyncStatus('error');
    }
  };

  // Helper to update an item in the queue
  const updateItem = (id: string, updates: Partial<MediaItem>) => {
    setMediaQueue(prev => prev.map(item => item.id === id ? { ...item, ...updates } : item));
    // Reset sync status on meaningful updates to trigger future saves
    // BUT only if completed, otherwise let the logic handle it
    if (updates.versions || updates.status) {
       setSyncStatus('idle'); 
    }
  };

  const addVersionToItem = (itemId: string, version: Version, setAsCurrent: boolean = true) => {
    setMediaQueue(prev => prev.map(item => {
      if (item.id !== itemId) return item;
      return {
        ...item,
        versions: [...item.versions, version],
        currentVersionId: setAsCurrent ? version.id : item.currentVersionId
      };
    }));
    setSyncStatus('idle'); // Needs save
  };

  // -------------------------------------------------------------------------
  // CORE LOGIC: Transcription Loop (Resumable)
  // -------------------------------------------------------------------------
  const startTranscription = async (item: MediaItem, isResuming = false) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    
    if (!item.file) {
      alert("فایل صوتی این پروژه در دسترس نیست و قابل پردازش مجدد نمی‌باشد.");
      return;
    }

    // Determine Start Point
    const startIndex = item.processedChunks || 0;
    
    updateItem(item.id, { 
      status: 'processing', 
      error: undefined // Clear previous errors
    });

    // Handle Versioning
    let baseVersionId: string;
    let fullTranscript = "";
    let initialVersions = [...item.versions];

    if (isResuming && item.versions.length > 0) {
      // Find existing RAW version to append to
      const existingRaw = item.versions.find(v => v.stage === ProcessingStage.RAW);
      if (existingRaw) {
        baseVersionId = existingRaw.id;
        fullTranscript = existingRaw.content;
      } else {
        // Fallback (shouldn't happen in valid resume)
        baseVersionId = uuidv4();
        const newVer = {
          id: baseVersionId,
          stage: ProcessingStage.RAW,
          name: 'متن خام (ادامه...)',
          content: '', 
          parentId: null,
          timestamp: Date.now()
        };
        addVersionToItem(item.id, newVer);
        initialVersions.push(newVer);
      }
    } else {
      // New Process
      if (item.processedChunks > 0 && !confirm("آیا می‌خواهید پردازش قبلی را ادامه دهید؟ (Cancel = شروع مجدد)")) {
         // Reset if user wants fresh start
         updateItem(item.id, { processedChunks: 0, totalChunks: 0 });
         return startTranscription({...item, processedChunks: 0}, false);
      }
      
      // If start index is 0, create new version
      if (startIndex === 0) {
        baseVersionId = uuidv4();
        const newVer = {
          id: baseVersionId,
          stage: ProcessingStage.RAW,
          name: 'متن خام (در حال تولید...)',
          content: '', 
          parentId: null,
          timestamp: Date.now()
        };
        addVersionToItem(item.id, newVer);
        initialVersions.push(newVer);
      } else {
         // Resuming logic (same as above block really)
         const existingRaw = item.versions.find(v => v.stage === ProcessingStage.RAW);
         baseVersionId = existingRaw?.id || uuidv4();
         fullTranscript = existingRaw?.content || "";
      }
    }

    try {
      // 1. Decode Audio locally
      let currentDuration = item.duration;
      let currentTotalChunks = item.totalChunks;

      if (startIndex === 0 || !item.duration) {
          console.log('Decoding audio...');
          const audioBuffer = await decodeAudioFile(item.file);
          currentDuration = audioBuffer.duration;
          currentTotalChunks = Math.ceil(currentDuration / CHUNK_DURATION);
          updateItem(item.id, { duration: currentDuration, totalChunks: currentTotalChunks });
      }

      // Re-decode for slicing (Optimization: could cache this in memory if not reload)
      const audioBuffer = await decodeAudioFile(item.file);
      
      // Ensure we have total chunks
      if (!currentTotalChunks) {
         currentTotalChunks = Math.ceil(audioBuffer.duration / CHUNK_DURATION);
      }

      let completedSuccessfully = true;

      // 3. Loop through chunks starting from where we left off
      for (let i = startIndex; i < currentTotalChunks; i++) {
        // Check if status changed to paused externally (e.g. user clicked pause)
        // We need to check the ref because closure state 'item' is stale
        const currentItemState = mediaQueueRef.current.find(x => x.id === item.id);
        if (currentItemState?.status === 'paused' && !currentItemState.error) {
           completedSuccessfully = false;
           break; // User manually paused
        }

        const startTime = i * CHUNK_DURATION;

        // UI Update: Processing chunk i+1
        const currentProgress = Math.round((i / currentTotalChunks) * 100);
        updateItem(item.id, { progress: currentProgress });

        // Slice & Convert
        const chunkBlob = await sliceAudioBuffer(audioBuffer, startTime, CHUNK_DURATION);
        const chunkBase64 = await blobToBase64(chunkBlob);

        // Call Gemini
        const chunkText = await transcribeSegment(
          apiKey, 
          chunkBase64, 
          'audio/mp3',
          selectedModel
        );
        
        fullTranscript += chunkText + " ";

        // CRITICAL: Update state ONLY after success
        // Increment processedChunks so next time we resume from i + 1
        const nextProgress = Math.round(((i + 1) / currentTotalChunks) * 100);
        updateItem(item.id, { processedChunks: i + 1, progress: nextProgress });

        // Update Version Content Live
        setMediaQueue(prev => prev.map(qItem => {
          if (qItem.id !== item.id) return qItem;
          return {
            ...qItem,
            versions: qItem.versions.map(v => 
              v.id === baseVersionId ? { ...v, content: fullTranscript, name: 'متن خام (در حال تکمیل)' } : v
            )
          };
        }));
      }

      // Completion Check
      // Use local flag instead of stale ref for immediate update
      if (completedSuccessfully) {
        updateItem(item.id, { status: 'completed', progress: 100 });
        setMediaQueue(prev => prev.map(qItem => {
          if (qItem.id !== item.id) return qItem;
          return {
            ...qItem,
            versions: qItem.versions.map(v => v.id === baseVersionId ? { ...v, name: 'متن خام (کامل)' } : v)
          };
        }));

        // --- EXPLICIT SAVE ONLY ON COMPLETION ---
        // We need to construct the full object because 'item' variable is stale
        const finalVersions = initialVersions.map(v => 
            v.id === baseVersionId ? { ...v, content: fullTranscript, name: 'متن خام (کامل)' } : v
        );
        // If initialVersions didn't have it (weird case), allow for safety
        if (!finalVersions.find(v => v.id === baseVersionId)) {
             finalVersions.push({
                 id: baseVersionId,
                 stage: ProcessingStage.RAW,
                 name: 'متن خام (کامل)',
                 content: fullTranscript,
                 parentId: null,
                 timestamp: Date.now()
             });
        }

        const finalItemToSave: MediaItem = {
            ...item,
            status: 'completed',
            progress: 100,
            duration: currentDuration,
            totalChunks: currentTotalChunks,
            processedChunks: currentTotalChunks,
            versions: finalVersions,
            currentVersionId: baseVersionId
        };

        handleSaveToCloud(finalItemToSave, true);
      }

    } catch (err: any) {
      console.error("Transcription interrupted:", err);
      
      // PAUSE on error instead of failing completely
      const errorMessage = err.message || "خطا در برقراری ارتباط";
      
      updateItem(item.id, { 
        status: 'paused', 
        error: errorMessage,
        progress: item.progress 
      });
      
      // DO NOT SAVE HERE. 
      // User request: "Do not save... until implementation is finished"
    }
  };

  // -------------------------------------------------------------------------
  // STAGE LOGIC: Post-processing
  // -------------------------------------------------------------------------
  const runStage = async (stage: ProcessingStage, parentVersionId: string, customPrompt?: string) => {
    if (!activeItem || !apiKey) return;

    const parentVersion = activeItem.versions.find(v => v.id === parentVersionId);
    if (!parentVersion) return;

    const newVersionId = uuidv4();
    let stageName = '';
    switch(stage) {
      case ProcessingStage.ARABIC: stageName = 'اعراب‌گذاری شده'; break;
      case ProcessingStage.TITLES: stageName = 'عنوان‌بندی شده'; break;
      case ProcessingStage.FORMAL: stageName = 'رسمی شده'; break;
      case ProcessingStage.CUSTOM: stageName = 'ویرایش سفارشی'; break;
    }

    const newVersion: Version = {
      id: newVersionId,
      stage,
      name: `${stageName} (در حال پردازش...)`,
      content: 'لطفاً صبر کنید...',
      parentId: parentVersionId,
      timestamp: Date.now(),
      promptUsed: customPrompt
    };

    addVersionToItem(activeItem.id, newVersion);
    updateItem(activeItem.id, { status: 'processing', progress: 0 });

    const progressInterval = setInterval(() => {
      setMediaQueue(prev => {
        const item = prev.find(i => i.id === activeItem.id);
        if (!item || item.status !== 'processing') return prev;
        const nextProgress = Math.min(item.progress + 5, 95);
        return prev.map(i => i.id === activeItem.id ? { ...i, progress: nextProgress } : i);
      });
    }, 800);

    try {
      const result = await processTextStage(
        apiKey, 
        parentVersion.content, 
        stage, 
        selectedModel,
        customPrompt
      );
      
      clearInterval(progressInterval);
      
      setMediaQueue(prev => prev.map(qItem => {
        if (qItem.id !== activeItem.id) return qItem;
        return {
          ...qItem,
          status: 'completed',
          progress: 100,
          versions: qItem.versions.map(v => 
            v.id === newVersionId ? { ...v, content: result, name: stageName } : v
          )
        };
      }));
      setSyncStatus('idle');

      // EXPLICIT SAVE after stage completion
      // Since 'activeItem' is stale, we construct the item with the new version
      const finalVersions = [...activeItem.versions, { ...newVersion, content: result, name: stageName }];
      const finalItemToSave: MediaItem = {
          ...activeItem,
          status: 'completed',
          progress: 100,
          versions: finalVersions
      };
      handleSaveToCloud(finalItemToSave, true);

    } catch (err) {
      clearInterval(progressInterval);
      updateItem(activeItem.id, { status: 'error', progress: 0 });
      setMediaQueue(prev => prev.map(qItem => {
        if (qItem.id !== activeItem.id) return qItem;
        return {
          ...qItem,
          versions: qItem.versions.map(v => 
            v.id === newVersionId ? { ...v, content: 'خطا در پردازش. لطفا مجدد تلاش کنید.', name: `${stageName} (ناموفق)` } : v
          )
        };
      }));
    }
  };

  // -------------------------------------------------------------------------
  // AUTO-NEXT LOGIC
  // -------------------------------------------------------------------------
  const handlePlaybackEnded = () => {
    const currentIndex = mediaQueue.findIndex(i => i.id === activeItemId);
    if (currentIndex >= 0 && currentIndex < mediaQueue.length - 1) {
      setActiveItemId(mediaQueue[currentIndex + 1].id);
    }
  };

  // -------------------------------------------------------------------------
  // TEXT MANAGEMENT (Copy/Export/Edit)
  // -------------------------------------------------------------------------
  const getCurrentVersion = () => activeItem?.versions.find(v => v.id === activeItem.currentVersionId);
  
  const handleContentUpdate = (newContent: string) => {
    if (activeItem && activeItem.currentVersionId) {
       setMediaQueue(prev => prev.map(qItem => {
         if (qItem.id !== activeItem.id) return qItem;
         return {
           ...qItem,
           versions: qItem.versions.map(v => 
             v.id === activeItem.currentVersionId ? { ...v, content: newContent } : v
           )
         };
       }));
       setSyncStatus('idle');
    }
  };

  const getHtmlContent = (content: string) => {
    const isHtml = /^\s*<[a-z]/i.test(content);
    if (isHtml) return content;
    return marked.parse(content, { breaks: true }) as string;
  };

  const copyToClipboard = async () => {
    const version = getCurrentVersion();
    if (!version) return;

    const htmlContent = getHtmlContent(version.content);

    try {
      const blobHtml = new Blob([htmlContent], { type: 'text/html' });
      const blobText = new Blob([version.content], { type: 'text/plain' });
      
      const clipboardItem = new ClipboardItem({ 
        'text/html': blobHtml,
        'text/plain': blobText 
      });
      
      await navigator.clipboard.write([clipboardItem]);
      
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      navigator.clipboard.writeText(version.content);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    }
  };

  const exportToWord = () => {
    const version = getCurrentVersion();
    if (!version || !activeItem) return;

    const stagePrefixMap: Record<ProcessingStage, string> = {
      [ProcessingStage.RAW]: 'متن خام',
      [ProcessingStage.ARABIC]: 'اعراب شده ی',
      [ProcessingStage.TITLES]: 'عنوان بندی شده ی',
      [ProcessingStage.FORMAL]: 'رسمی شده ی',
      [ProcessingStage.CUSTOM]: 'ویرایش شده ی',
    };

    const prefix = stagePrefixMap[version.stage] || 'خروجی';
    const itemName = (activeItem as any).fileName || activeItem.file?.name || 'فایل';
    const originalName = itemName.replace(/\.[^/.]+$/, "");
    const timeStr = new Date().toLocaleTimeString('fa-IR').replace(/:/g, '-');
    const fileName = `${prefix} ${originalName} ساعت ${timeStr}.doc`;

    const contentBody = getHtmlContent(version.content);

    const preHtml = `<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'><head><meta charset='utf-8'><title>Export</title>
    <style>
      body { font-family: 'Tahoma', 'Vazirmatn', sans-serif; direction: rtl; text-align: right; }
      h1, h2, h3, h4, h5, h6 { font-weight: bold; color: #1e293b; margin-top: 1em; margin-bottom: 0.5em; }
      h1 { font-size: 24pt; }
      h2 { font-size: 18pt; border-bottom: 2px solid #e2e8f0; }
      h3 { font-size: 14pt; }
      p { font-size: 12pt; line-height: 1.5; margin-bottom: 1em; }
      strong, b { font-weight: bold; color: #000; }
      blockquote { background: #f8fafc; padding: 10px; border-right: 4px solid #6366f1; margin: 10px 0; font-style: italic; }
    </style>
    </head><body>`;
    const postHtml = "</body></html>";
    const html = preHtml + contentBody + postHtml;

    const blob = new Blob(['\ufeff', html], {
        type: 'application/msword'
    });
    
    saveAs(blob, fileName);
  };

  // -------------------------------------------------------------------------
  // RENDER
  // -------------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 font-sans" dir="rtl">
      
      {/* File Manager Modal */}
      <FileManager 
         isOpen={showFileManager} 
         onClose={() => setShowFileManager(false)} 
         onLoadProject={handleLoadProject}
      />

      {/* API Key Modal */}
      {showKeyModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-white p-6 rounded-2xl shadow-2xl w-96 max-w-full m-4 text-center">
            <Key className="mx-auto text-indigo-500 mb-4" size={48} />
            <h2 className="text-xl font-bold mb-2">تنظیم کلید دسترسی</h2>
            <p className="text-sm text-slate-500 mb-4">برای استفاده از برنامه، لطفا کلید API خود را وارد کنید.</p>
            <input 
              type="password" 
              placeholder="Google Gemini API Key"
              className="w-full p-3 rounded border border-slate-300 mb-4 text-left font-mono text-sm focus:ring-2 ring-indigo-500 outline-none"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button 
              onClick={() => { if(apiKey) setShowKeyModal(false); }}
              className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 transition"
            >
              ذخیره و ورود
            </button>
            <div className="mt-4 text-xs text-slate-400">
               اگر کلید ندارید، از <a href="https://aistudio.google.com/" target="_blank" className="text-indigo-500 underline">Google AI Studio</a> دریافت کنید.
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <header className="bg-white border-b border-slate-200 h-16 flex items-center px-4 md:px-6 justify-between sticky top-0 z-30 shadow-sm">
        <div className="flex items-center gap-3">
           <div className="bg-indigo-600 p-2 rounded-lg text-white shadow-lg shadow-indigo-200 hidden md:block">
             <FileAudio size={24} />
           </div>
           <div>
             <h1 className="font-bold text-sm md:text-lg text-slate-800">مبدل هوشمند صوتی</h1>
             <p className="text-[10px] text-slate-500 hidden md:block">Gemini Engine</p>
           </div>
        </div>
        
        <div className="flex items-center gap-2 md:gap-4">
            {/* Model Selector */}
            <div className="relative group">
              <div className="flex items-center gap-2 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded-lg transition cursor-pointer border border-transparent hover:border-slate-300">
                <Sparkles size={16} className="text-indigo-500" />
                <select 
                  className="bg-transparent text-xs font-medium text-slate-700 focus:outline-none appearance-none cursor-pointer w-32 md:w-auto"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  dir="ltr"
                >
                  {AVAILABLE_MODELS.map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="text-slate-400" />
              </div>
            </div>

            <div className="h-6 w-px bg-slate-200 hidden md:block"></div>

            <button 
              onClick={() => setShowFileManager(true)}
              className="flex items-center gap-2 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 px-3 py-2 rounded-lg transition text-xs md:text-sm font-medium"
            >
              <Layout size={18} />
              <span className="hidden md:inline">کتابخانه</span>
            </button>

            <label className="cursor-pointer bg-slate-800 hover:bg-slate-900 text-white px-3 py-2 rounded-lg flex items-center gap-2 transition text-xs md:text-sm font-medium shadow-md shadow-slate-300">
              <Upload size={18} />
              <span className="hidden md:inline">فایل جدید</span>
              <input type="file" multiple accept="audio/*,video/*" className="hidden" onChange={handleFileUpload} />
            </label>
        </div>
      </header>

      <div className="container mx-auto p-4 md:p-6 h-[calc(100vh-64px)] flex flex-col md:flex-row gap-6">
        
        {/* LEFT COLUMN: Sidebar Queue */}
        <aside className="w-full md:w-64 bg-white rounded-xl shadow border border-slate-200 flex flex-col overflow-hidden shrink-0">
          <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2 text-slate-700 font-semibold">
            <List size={18} />
            <span>لیست پخش</span>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-2">
            {mediaQueue.length === 0 && (
              <div className="text-center p-8 text-slate-400 text-sm">
                هیچ فایلی موجود نیست.<br/>فایلی آپلود کنید یا از کتابخانه باز کنید.
              </div>
            )}
            {mediaQueue.map((item) => (
              <div 
                key={item.id}
                onClick={() => setActiveItemId(item.id)}
                className={`p-3 rounded-lg cursor-pointer transition flex items-center justify-between group ${activeItemId === item.id ? 'bg-indigo-600 text-white shadow-md' : 'hover:bg-slate-50 text-slate-600'}`}
              >
                <div className="flex items-center gap-3 overflow-hidden">
                  {item.status === 'processing' ? <Loader2 className="animate-spin" size={16} /> : 
                   item.status === 'paused' ? <WifiOff size={16} className="text-amber-300" /> :
                   <FileAudio size={16} />}
                  
                  <div className="flex flex-col min-w-0">
                    <span className="truncate text-xs font-medium">{(item as any).fileName || item.file?.name || 'فایل بدون نام'}</span>
                    <span className={`text-[10px] ${activeItemId === item.id ? 'text-indigo-200' : 'text-slate-400'}`}>
                      {item.status === 'idle' && 'در انتظار'}
                      {item.status === 'processing' && `در حال پردازش (MP3)...`}
                      {item.status === 'paused' && 'توقف (قطع ارتباط)'}
                      {item.status === 'completed' && 'تکمیل شده'}
                      {item.status === 'error' && 'خطا'}
                    </span>
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  {(item.status === 'idle' || item.status === 'paused') && item.file && (
                     <button 
                       onClick={(e) => {
                         e.stopPropagation();
                         startTranscription(item, item.status === 'paused');
                       }}
                       className={`p-1.5 rounded-full transition-colors ${activeItemId === item.id ? 'text-indigo-100 hover:bg-indigo-500' : 'text-indigo-600 hover:bg-indigo-100'}`}
                       title={item.status === 'paused' ? "ادامه پردازش" : "شروع پیاده‌سازی"}
                     >
                       <Play size={16} fill="currentColor" />
                     </button>
                  )}
                  {activeItemId === item.id && item.status !== 'idle' && item.status !== 'paused' && <ArrowRight size={14} />}
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* MIDDLE COLUMN: Main Content */}
        <main className="flex-1 flex flex-col gap-4 min-w-0">
          
          {/* Player Area */}
          <div className="shrink-0 z-20">
             <MediaPlayer 
                file={activeItem?.file || null} 
                fileName={(activeItem as any)?.fileName}
                onEnded={handlePlaybackEnded}
             />
          </div>

          {/* Text Area */}
          <div className="flex-1 bg-white rounded-xl shadow border border-slate-200 flex flex-col overflow-hidden relative">
            <div className="p-3 border-b border-slate-100 bg-slate-50 flex flex-col gap-2">
              <div className="flex justify-between items-center">
                <h3 className="font-bold text-slate-700 flex items-center gap-2">
                  <FileText size={18} className="text-indigo-500" />
                  {activeItem 
                    ? getCurrentVersion()?.name || 'خروجی متن'
                    : 'خروجی متن'
                  }
                </h3>
                
                <div className="flex items-center gap-2">
                   {/* Sync Indicator */}
                   {activeItem && (
                     <div className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-slate-100 text-slate-500 ml-2" title={
                       syncStatus === 'saved' ? 'تغییرات ذخیره شد' : 
                       syncStatus === 'saving' ? 'در حال ذخیره...' : 
                       syncStatus === 'error' ? 'خطا در ذخیره' : 'تغییرات ذخیره نشده'
                     }>
                       {syncStatus === 'saving' ? <Loader2 size={12} className="animate-spin" /> : 
                        syncStatus === 'saved' ? <Cloud size={12} className="text-green-500" /> :
                        syncStatus === 'error' ? <CloudFog size={12} className="text-red-500" /> :
                        <Save size={12} className="text-slate-400" />
                       }
                       <span className="hidden sm:inline">
                         {syncStatus === 'saved' ? 'ذخیره شد' : 
                          syncStatus === 'saving' ? 'ذخیره...' : 
                          syncStatus === 'error' ? 'خطا' : 'آماده'}
                       </span>
                     </div>
                   )}

                   {/* Action Buttons */}
                   {activeItem && getCurrentVersion() && (
                     <>
                        <button 
                          onClick={() => handleSaveToCloud(activeItem)}
                          className="p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-600 rounded-md transition tooltip-trigger"
                          title="ذخیره دستی در ابر"
                        >
                           <Save size={18} />
                        </button>
                        <div className="w-px h-4 bg-slate-300 mx-1"></div>
                        <button 
                          onClick={copyToClipboard}
                          className="p-1.5 text-slate-500 hover:bg-slate-100 rounded-md transition tooltip-trigger relative"
                          title="کپی متن"
                        >
                           {copySuccess ? <Check size={18} className="text-green-600" /> : <Copy size={18} />}
                        </button>
                        <button 
                          onClick={exportToWord}
                          className="p-1.5 text-slate-500 hover:bg-slate-100 rounded-md transition tooltip-trigger"
                          title="دانلود فایل Word"
                        >
                           <Download size={18} />
                        </button>
                     </>
                   )}
                </div>
              </div>

              {/* Progress Bar */}
              {activeItem && activeItem.status === 'processing' && (
                <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden mt-1 relative">
                  <div 
                    className="h-full bg-indigo-500 transition-all duration-300 ease-out"
                    style={{ width: `${activeItem.progress}%` }}
                  ></div>
                  <div className="absolute top-0 right-0 left-0 bottom-0 flex items-center justify-center text-[9px] text-slate-500 font-mono leading-none">
                    {activeItem.progress}%
                  </div>
                </div>
              )}
            </div>
            
            <div className="flex-1 overflow-hidden relative">
               {activeItem ? (
                  <RichTextEditor 
                    content={getCurrentVersion()?.content || ''}
                    onContentChange={handleContentUpdate}
                    isReadOnly={activeItem.status === 'processing'}
                    placeholder={activeItem.status === 'idle' ? 'برای شروع پردازش دکمه پخش را بزنید...' : 'متن اینجا ظاهر می‌شود...'}
                  />
               ) : (
                 <div className="flex items-center justify-center h-full text-slate-400">
                   یک فایل را انتخاب کنید تا متن آن اینجا نمایش داده شود.
                 </div>
               )}

               {/* Empty State Overlay */}
               {activeItem && activeItem.status === 'idle' && !getCurrentVersion()?.content && activeItem.file && (
                   <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/80 z-10">
                     <p className="mb-4 text-slate-500 text-sm">فایل آماده پردازش است.</p>
                     <button 
                       onClick={() => startTranscription(activeItem)}
                       className="bg-indigo-600 text-white px-6 py-2 rounded-full hover:bg-indigo-700 transition shadow-lg shadow-indigo-200 flex items-center gap-2 active:scale-95"
                     >
                       <Play size={18} fill="currentColor" />
                       <span>شروع پیاده‌سازی</span>
                     </button>
                   </div>
               )}

               {/* Paused/Error State Overlay */}
               {activeItem && activeItem.status === 'paused' && (
                   <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/90 z-10 backdrop-blur-sm">
                     <div className="bg-amber-50 p-6 rounded-2xl shadow-xl border border-amber-100 max-w-sm text-center">
                        <WifiOff size={32} className="mx-auto text-amber-500 mb-3" />
                        <h3 className="font-bold text-slate-800 mb-1">ارتباط قطع شد</h3>
                        <p className="text-sm text-slate-500 mb-4">
                           پردازش موقتا متوقف شده است. به محض اتصال مجدد اینترنت، برنامه خودکار ادامه خواهد داد.
                        </p>
                        <button 
                          onClick={() => startTranscription(activeItem, true)}
                          className="bg-indigo-600 text-white px-6 py-2 rounded-lg hover:bg-indigo-700 transition w-full flex items-center justify-center gap-2"
                        >
                          <Play size={16} fill="currentColor" />
                          <span>تلاش مجدد دستی</span>
                        </button>
                        {activeItem.error && (
                          <div className="mt-3 text-[10px] text-slate-400 font-mono bg-white p-2 rounded border border-slate-100 break-all">
                             {activeItem.error.substring(0, 100)}...
                          </div>
                        )}
                     </div>
                   </div>
               )}

            </div>
          </div>

        </main>

        {/* RIGHT COLUMN: Action Sidebar */}
        {activeItem && (
          <aside className="w-full md:w-80 shrink-0 h-[400px] md:h-auto">
             <StageManager 
                item={activeItem} 
                onRunStage={runStage}
                onViewVersion={(v) => updateItem(activeItem.id, { currentVersionId: v.id })}
             />
          </aside>
        )}
      </div>
    </div>
  );
};

export default App;