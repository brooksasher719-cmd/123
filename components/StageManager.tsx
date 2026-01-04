import React, { useState } from 'react';
import { 
  Play, 
  RotateCcw, 
  Eye, 
  FileText, 
  Languages, 
  ListTree, 
  ScrollText, 
  Wand2,
  CheckCircle2,
  ChevronDown
} from 'lucide-react';
import { MediaItem, ProcessingStage, Version } from '../types';

interface StageManagerProps {
  item: MediaItem;
  onRunStage: (stage: ProcessingStage, parentVersionId: string, customPrompt?: string) => void;
  onViewVersion: (version: Version) => void;
}

const StageManager: React.FC<StageManagerProps> = ({ item, onRunStage, onViewVersion }) => {
  const [expandedStage, setExpandedStage] = useState<ProcessingStage | null>(null);
  const [selectedParentId, setSelectedParentId] = useState<string>(item.currentVersionId || '');
  const [customPrompt, setCustomPrompt] = useState('');

  // Group versions by stage for display
  const getVersionsByStage = (stage: ProcessingStage) => {
    return item.versions.filter(v => v.stage === stage);
  };

  const stages = [
    { 
      id: ProcessingStage.RAW, 
      label: 'پیاده‌سازی اولیه (متن خام)', 
      icon: FileText,
      description: 'تبدیل کلمه به کلمه صوت به متن'
    },
    { 
      id: ProcessingStage.ARABIC, 
      label: 'اعراب‌گذاری و متون عربی', 
      icon: Languages,
      description: 'بولد کردن و گیومه‌گذاری متون عربی'
    },
    { 
      id: ProcessingStage.TITLES, 
      label: 'عنوان‌بندی درختی', 
      icon: ListTree,
      description: 'افزودن ساختار و عناوین گویا'
    },
    { 
      id: ProcessingStage.FORMAL, 
      label: 'رسمی‌سازی (کلمه به کلمه)', 
      icon: ScrollText,
      description: 'تبدیل محاوره به رسمی بدون خلاصه'
    },
    { 
      id: ProcessingStage.CUSTOM, 
      label: 'ویرایش با پرامپت سفارشی', 
      icon: Wand2,
      description: 'اعمال دستورات خاص شما'
    },
  ];

  const handleRunClick = (stageId: ProcessingStage) => {
    if (stageId === ProcessingStage.RAW) return; // Raw is automatic
    setExpandedStage(expandedStage === stageId ? null : stageId);
    // Reset selected parent to current view to encourage chaining
    if (item.currentVersionId) {
      setSelectedParentId(item.currentVersionId);
    }
  };

  const executeRun = (stageId: ProcessingStage) => {
    if (!selectedParentId) return;
    onRunStage(stageId, selectedParentId, stageId === ProcessingStage.CUSTOM ? customPrompt : undefined);
    setExpandedStage(null);
  };

  const getParentName = (id: string) => {
    const v = item.versions.find(ver => ver.id === id);
    return v ? `${v.name} (${new Date(v.timestamp).toLocaleTimeString('fa-IR')})` : 'نامشخص';
  };

  // Determine if stages can be run (must have at least one version/raw text)
  const canRunStages = item.versions && item.versions.length > 0;

  return (
    <div className="h-full flex flex-col bg-white rounded-xl shadow-lg border border-slate-200 overflow-hidden">
      <div className="p-4 bg-slate-100 border-b border-slate-200">
        <h3 className="font-bold text-slate-800 text-lg">مراحل پردازش</h3>
        <p className="text-xs text-slate-500 mt-1">مدیریت نسخه‌ها و اعمال تغییرات</p>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {stages.map((stage) => {
          const stageVersions = getVersionsByStage(stage.id);
          const isRaw = stage.id === ProcessingStage.RAW;
          const hasVersions = stageVersions.length > 0;

          return (
            <div key={stage.id} className={`border rounded-lg transition-all ${
              item.versions.find(v => v.id === item.currentVersionId)?.stage === stage.id 
                ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-200' 
                : 'border-slate-200 bg-white hover:border-indigo-300'
            }`}>
              {/* Header */}
              <div className="p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-full ${hasVersions ? 'bg-green-100 text-green-600' : 'bg-slate-100 text-slate-400'}`}>
                    <stage.icon size={18} />
                  </div>
                  <div>
                    <h4 className="font-semibold text-sm text-slate-700">{stage.label}</h4>
                    <span className="text-[10px] text-slate-500 block">{stage.description}</span>
                  </div>
                </div>
                
                {!isRaw && (
                  <button 
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation();
                        handleRunClick(stage.id);
                    }}
                    className="p-2 hover:bg-slate-100 rounded-full text-indigo-600 transition-colors tooltip-trigger disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:text-slate-400"
                    title={canRunStages ? "اجرای عملیات جدید" : "ابتدا باید پیاده‌سازی متن خام را انجام دهید"}
                    disabled={!canRunStages} 
                  >
                    <RotateCcw size={18} />
                  </button>
                )}
              </div>

              {/* Action Panel (Dropdown for running) */}
              {expandedStage === stage.id && (
                <div className="p-3 bg-slate-50 border-t border-slate-200 animate-in slide-in-from-top-2">
                  <div className="mb-3">
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      انتخاب متن منبع برای پردازش:
                    </label>
                    <select 
                      className="w-full text-xs p-2 rounded border border-slate-300 bg-white"
                      value={selectedParentId}
                      onChange={(e) => setSelectedParentId(e.target.value)}
                    >
                      <option value="" disabled>انتخاب کنید...</option>
                      {item.versions.map(v => (
                        <option key={v.id} value={v.id}>
                          {v.name} - {new Date(v.timestamp).toLocaleTimeString('fa-IR')}
                        </option>
                      ))}
                    </select>
                  </div>

                  {stage.id === ProcessingStage.CUSTOM && (
                     <div className="mb-3">
                       <label className="block text-xs font-medium text-slate-600 mb-1">
                         دستور (Prompt) شما:
                       </label>
                       <textarea 
                        className="w-full text-xs p-2 rounded border border-slate-300 min-h-[60px]"
                        placeholder="مثلا: تمام افعال را به زمان گذشته برگردان..."
                        value={customPrompt}
                        onChange={(e) => setCustomPrompt(e.target.value)}
                       />
                     </div>
                  )}

                  <button 
                    type="button"
                    onClick={() => executeRun(stage.id)}
                    disabled={!selectedParentId}
                    className="w-full bg-indigo-600 text-white text-xs py-2 rounded shadow-sm hover:bg-indigo-700 flex items-center justify-center gap-2 disabled:opacity-50 transition-colors"
                  >
                    <Play size={14} />
                    شروع پردازش
                  </button>
                </div>
              )}

              {/* Version History List */}
              {hasVersions && (
                <div className="border-t border-slate-100 divide-y divide-slate-100">
                  {stageVersions.map((ver, idx) => (
                    <div 
                      key={ver.id} 
                      className={`p-2 flex items-center justify-between text-xs hover:bg-slate-50 cursor-pointer ${item.currentVersionId === ver.id ? 'bg-indigo-50 font-medium' : ''}`}
                      onClick={() => onViewVersion(ver)}
                    >
                      <div className="flex flex-col">
                        <span className="text-slate-700">نسخه {idx + 1}</span>
                        <span className="text-[10px] text-slate-400">منبع: {ver.parentId ? 'نسخه قبلی' : 'صوت اصلی'}</span>
                      </div>
                      <div className="flex gap-2">
                        {item.currentVersionId === ver.id && <CheckCircle2 size={14} className="text-green-500" />}
                        <Eye size={14} className="text-slate-400 hover:text-indigo-500" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default StageManager;